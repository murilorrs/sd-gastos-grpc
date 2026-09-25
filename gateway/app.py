"""API Gateway — a única porta de entrada do sistema.

Recebe HTTP/JSON, valida o payload, exige um JWT válido e traduz cada chamada
para gRPC/protobuf, despachando para o microsserviço dono do dado:

    POST /auth/token             -> (nenhum; emite o JWT)
    GET  /cards                  -> CardService.ListCards
    POST /cards                  -> CardService.RegisterCard
    GET  /cards/validate         -> CardService.ValidateCard
    POST /expenses               -> ExpenseService.RegisterExpense
    GET  /expenses               -> ExpenseService.SearchExpenses (stream)
    GET  /expenses/summary       -> ExpenseService.SummaryByGroup

Os microsserviços escutam só em 127.0.0.1: quem está fora da vm-server fala
com o Gateway, nunca com eles. Documentação interativa em /docs.

    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import functools
import hmac
import logging
import os
import secrets
import time
from typing import Annotated, Literal, Optional

import grpc
import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, StringConstraints

import expenses_pb2
import expenses_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("gateway")

# Sem JWT_SECRET no ambiente, sorteia um a cada início: funciona, mas os tokens
# emitidos deixam de valer quando o gateway reinicia. Em produção, defina-o.
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
if "JWT_SECRET" not in os.environ:
    log.warning("JWT_SECRET not set; using a random one for this run")
JWT_TTL_SECONDS = int(os.environ.get("JWT_TTL_SECONDS", "3600"))

# ---------------------------------------------------------------------------
# Validação do payload (requisito: 400 para dado inválido ou ausente)
# ---------------------------------------------------------------------------

Method = Literal["CREDIT", "DEBIT"]
# Lista fechada também no Gateway: o prompt da LLM já restringe as categorias,
# mas uma chamada direta à API não passa pelo prompt.
Category = Literal["food", "transport", "technology", "leisure", "health",
                   "housing", "education", "clothing", "other"]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                        max_length=120)]
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class Credentials(BaseModel):
    username: str
    password: str


class CardIn(BaseModel):
    name: Text
    method: Method


class ExpenseIn(BaseModel):
    product: Text
    description: Annotated[str, StringConstraints(max_length=500)] = ""
    amount: float = Field(gt=0, le=1_000_000_000)
    card: Text
    method: Method
    category: Category = "other"
    date: Optional[Annotated[str, StringConstraints(pattern=DATE_PATTERN)]] = None


app = FastAPI(title="Expense tracking gateway",
              description="HTTP/JSON in front of the gRPC microservices.")


@app.exception_handler(RequestValidationError)
async def bad_request(request, exc):
    """O FastAPI responde 422 por padrão; o enunciado pede 400."""
    problems = []
    for error in exc.errors():
        field = ".".join(str(p) for p in error["loc"] if p not in ("body", "query"))
        problems.append("%s: %s" % (field, error["msg"]) if field else error["msg"])
    return JSONResponse(status_code=400, content={"detail": "; ".join(problems)})


# ---------------------------------------------------------------------------
# Autenticação JWT (requisito: 401 na borda, antes de chegar a qualquer serviço)
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def require_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if credentials is None:
        raise HTTPException(401, "missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return claims["sub"]


@app.post("/auth/token")
def login(body: Credentials):
    """Troca usuário e senha por um JWT. Um único usuário, vindo do ambiente."""
    user = os.environ.get("GATEWAY_USER", "")
    password = os.environ.get("GATEWAY_PASSWORD", "")
    # compare_digest leva o mesmo tempo acertando ou errando, então a resposta
    # não revela quantos caracteres da senha estavam certos.
    valid = (bool(user and password)
             and hmac.compare_digest(body.username.encode(), user.encode())
             and hmac.compare_digest(body.password.encode(), password.encode()))
    if not valid:
        raise HTTPException(401, "invalid username or password")
    token = jwt.encode({"sub": body.username, "exp": int(time.time()) + JWT_TTL_SECONDS},
                       JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer",
            "expires_in": JWT_TTL_SECONDS}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tradução JSON <-> gRPC
# ---------------------------------------------------------------------------

METHOD_TO_PROTO = {"CREDIT": expenses_pb2.CREDIT, "DEBIT": expenses_pb2.DEBIT}
METHOD_FROM_PROTO = {v: k for k, v in METHOD_TO_PROTO.items()}

# Como cada falha do gRPC aparece para quem chamou em HTTP.
_HTTP_STATUS = {
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
}


@functools.lru_cache(maxsize=None)
def cards():
    channel = grpc.insecure_channel(os.environ.get("CARDS_ADDR", "localhost:50052"))
    return expenses_pb2_grpc.CardServiceStub(channel)


@functools.lru_cache(maxsize=None)
def expenses():
    channel = grpc.insecure_channel(os.environ.get("EXPENSES_ADDR", "localhost:50051"))
    return expenses_pb2_grpc.ExpenseServiceStub(channel)


def call(name, rpc, request, stream=False):
    """Serializa em protobuf, chama o microsserviço e traduz erros para HTTP."""
    log.info("%-16s JSON -> protobuf %d bytes", name, request.ByteSize())
    try:
        result = rpc(request, timeout=10)
        return list(result) if stream else result
    except grpc.RpcError as error:
        raise HTTPException(_HTTP_STATUS.get(error.code(), 502),
                            error.details() or error.code().name)


def card_json(card):
    return {"name": card.name,
            "methods": [METHOD_FROM_PROTO[m] for m in card.methods]}


def expense_json(e):
    return {"id": e.id, "product": e.product, "description": e.description,
            "amount": e.amount, "card": e.card,
            "method": METHOD_FROM_PROTO.get(e.method), "category": e.category,
            "date": e.date, "created_at": e.created_at}


def expense_filter(
    card: Optional[str] = None,
    method: Optional[Method] = None,
    category: Optional[Category] = None,
    start_date: Optional[str] = Query(None, pattern=DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=DATE_PATTERN),
):
    """Parâmetros de consulta comuns à busca e ao resumo."""
    return expenses_pb2.Filter(
        card=card or "", method=METHOD_TO_PROTO.get(method, 0),
        category=category or "", start_date=start_date or "",
        end_date=end_date or "")


# ---------------------------------------------------------------------------
# Rotas protegidas: toda rota daqui para baixo exige o JWT
# ---------------------------------------------------------------------------

api = APIRouter(dependencies=[Depends(require_token)])


@api.get("/cards")
def list_cards():
    response = call("ListCards", cards().ListCards, expenses_pb2.ListCardsRequest())
    return {"cards": [card_json(c) for c in response.cards]}


@api.post("/cards", status_code=201)
def register_card(body: CardIn):
    response = call("RegisterCard", cards().RegisterCard,
                    expenses_pb2.RegisterCardRequest(
                        name=body.name, method=METHOD_TO_PROTO[body.method]))
    content = {"message": response.message, "created": response.created}
    # Cartão que já existia não é criação: 200 em vez de 201.
    return content if response.created else JSONResponse(content, status_code=200)


@api.get("/cards/validate")
def validate_card(name: str = Query(min_length=1), method: Optional[Method] = None):
    response = call("ValidateCard", cards().ValidateCard,
                    expenses_pb2.ValidateCardRequest(
                        name=name, method=METHOD_TO_PROTO.get(method, 0)))
    return {"exists": response.exists, "name": response.name,
            "message": response.message,
            "suggestions": [card_json(c) for c in response.suggestions]}


@api.post("/expenses", status_code=201)
def register_expense(body: ExpenseIn):
    response = call("RegisterExpense", expenses().RegisterExpense,
                    expenses_pb2.RegisterExpenseRequest(
                        product=body.product, description=body.description,
                        amount=body.amount, card=body.card,
                        method=METHOD_TO_PROTO[body.method],
                        category=body.category, date=body.date or ""))
    if not response.ok:
        # O serviço de Gastos recusou: o cartão não existe naquele método.
        raise HTTPException(400, response.message)
    return {"message": response.message, "expense": expense_json(response.expense)}


@api.get("/expenses")
def search_expenses(filters=Depends(expense_filter)):
    found = call("SearchExpenses", expenses().SearchExpenses, filters, stream=True)
    return {"expenses": [expense_json(e) for e in found]}


@api.get("/expenses/summary")
def summary(group_by: Literal["category", "card", "method"] = "category",
            filters=Depends(expense_filter)):
    response = call("SummaryByGroup", expenses().SummaryByGroup,
                    expenses_pb2.SummaryRequest(group_by=group_by, filter=filters))
    return {"totals": [{"key": t.key, "total": t.total, "count": t.count}
                       for t in response.totals],
            "grand_total": response.grand_total}


app.include_router(api)
