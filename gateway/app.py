"""API Gateway — a única porta de entrada do sistema.

Recebe HTTP/JSON, valida o payload, exige um JWT válido e traduz cada chamada
para gRPC/protobuf, despachando para o microsserviço dono do dado:

    POST /auth/token             -> (nenhum; emite o JWT)
    GET  /meta                   -> (nenhum; listas fechadas para a interface)
    GET  /cards                  -> CardService.ListCards
    POST /cards                  -> CardService.RegisterCard
    GET  /cards/validate         -> CardService.ValidateCard
    POST /expenses               -> ExpenseService.RegisterExpense
    GET  /expenses               -> ExpenseService.SearchExpenses (stream)
    GET  /expenses/summary       -> ExpenseService.SummaryByGroup
    PUT  /expenses/{id}          -> ExpenseService.UpdateExpense
    DEL  /expenses/{id}          -> ExpenseService.DeleteExpense
    POST /nlu/interpret          -> Claude, e depois o RPC que o comando pedir

Os microsserviços escutam só em 127.0.0.1: quem está fora da vm-server fala
com o Gateway, nunca com eles. Documentação interativa em /docs.

    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import datetime
import functools
import hmac
import logging
import os
import secrets
import sys
import time
from typing import Annotated, Literal, Optional, get_args

import grpc
import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, StringConstraints

import expenses_pb2
import expenses_pb2_grpc

# O pacote language/ fica na raiz do repositório, um nível acima de gateway/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from language import nlu, period   # noqa: E402

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


class CommandIn(BaseModel):
    """O texto que o usuário digitou na interface web, em português."""
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                           max_length=500)]


app = FastAPI(title="Expense tracking gateway",
              description="HTTP/JSON in front of the gRPC microservices.")

# O navegador e o Gateway têm sempre a mesma origem: em produção o nginx da
# vm-client serve o frontend e repassa /api para cá, e em desenvolvimento o
# proxy do Vite faz o mesmo. Nenhuma requisição da interface é cross-origin, e
# este middleware é rede de segurança — para quem apontar um frontend direto
# para o Gateway, sem proxy. CORS_ORIGINS restringe a lista quando se quer;
# como a autenticação é por cabeçalho e não por cookie, credentials fica
# desligado de propósito.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
# O prompt do modelo fala "credit"/"debit" minúsculos; o contrato HTTP fala
# "CREDIT"/"DEBIT". Os dois dicionários abaixo fazem a ponte nas duas direções.
METHOD_LABEL = {v: k.lower() for k, v in METHOD_TO_PROTO.items()}
METHOD_FROM_LABEL = {k.lower(): k for k in METHOD_TO_PROTO}

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


@api.put("/expenses/{expense_id}")
def update_expense(body: ExpenseIn,
                   expense_id: int = Path(gt=0, description="id do gasto")):
    """Altera um gasto. O corpo é o gasto inteiro, como ele deve ficar."""
    response = call("UpdateExpense", expenses().UpdateExpense,
                    expenses_pb2.UpdateExpenseRequest(
                        id=expense_id, product=body.product,
                        description=body.description, amount=body.amount,
                        card=body.card, method=METHOD_TO_PROTO[body.method],
                        category=body.category, date=body.date or ""))
    if not response.ok:
        raise HTTPException(400, response.message)
    return {"message": response.message, "expense": expense_json(response.expense)}


@api.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int = Path(gt=0, description="id do gasto")):
    response = call("DeleteExpense", expenses().DeleteExpense,
                    expenses_pb2.DeleteExpenseRequest(id=expense_id))
    return {"message": response.message}


@api.get("/meta")
def meta():
    """As listas fechadas que a interface usa para montar os formulários.

    Elas já existem aqui como tipos Literal — publicá-las evita que o frontend
    mantenha uma segunda cópia que sai de sincronia com a validação real.
    """
    return {
        "methods": list(METHOD_TO_PROTO),
        "categories": list(get_args(Category)),
        "periods": list(period.PERIOD_LABELS),
        "group_by": ["category", "card", "method"],
        "nlu": {"enabled": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "model": nlu.model_name()},
    }


# ---------------------------------------------------------------------------
# Linguagem natural
#
# O texto vira um comando estruturado ({"action", "args"}) e o Gateway despacha
# esse comando pelos mesmos RPCs das rotas acima — nenhum microsserviço sabe
# que existe um modelo de linguagem. Sem ANTHROPIC_API_KEY, ou se a API falhar,
# cai no interpretador por regras de language/nlu.py: a demonstração não
# depende da rede até a Anthropic.
# ---------------------------------------------------------------------------

def _labeled_cards():
    """Cartões reais, como o prompt do modelo os espera: [(nome, ['credit'])]."""
    response = call("ListCards", cards().ListCards, expenses_pb2.ListCardsRequest())
    return [(c.name, [METHOD_LABEL[m] for m in c.methods]) for c in response.cards]


def _interpret(text, cards_list):
    """Texto -> (comando, qual interpretador respondeu, motivo da queda).

    A queda para o interpretador offline é informada na resposta em vez de
    silenciosa: numa apresentação, saber que a LLM ficou fora do ar importa
    tanto quanto o comando ter funcionado.
    """
    today = datetime.date.today().isoformat()
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return nlu.interpret(text, cards_list, today), "claude", None
        except Exception as error:      # noqa: BLE001 - qualquer falha cai no offline
            log.warning("nlu: %s", nlu.explain(error))
            return (nlu.interpret_offline(text, cards_list, today), "offline",
                    nlu.explain(error))
    return nlu.interpret_offline(text, cards_list, today), "offline", "no API key"


def _resolve_card(name, method, registered):
    """Confere o cartão no CardService antes de qualquer gravação.

    Devolve (name, method, problema). `problema` é None quando o par existe;
    caso contrário é o dict que a interface usa para oferecer as saídas —
    corrigir para um cartão cadastrado, ou cadastrar o novo e lançar nele.
    """
    if not name:
        return None, None, {"status": "needs_card",
                            "message": "which card was it?",
                            "suggestions": [{"name": n, "methods": m}
                                            for n, m in registered]}

    found = call("ValidateCard", cards().ValidateCard,
                 expenses_pb2.ValidateCardRequest(name=name))
    if not found.exists:
        return None, None, {"status": "needs_card", "message": found.message,
                            "suggestions": [card_json(c) for c in found.suggestions]}

    name = found.name
    available = dict((n, m) for n, m in registered).get(name, [])
    if method:
        pair = call("ValidateCard", cards().ValidateCard,
                    expenses_pb2.ValidateCardRequest(
                        name=name, method=METHOD_TO_PROTO[method]))
        if not pair.exists:
            return None, None, {"status": "needs_method", "message": pair.message,
                                "suggestions": [{"name": name, "methods":
                                                 [METHOD_FROM_LABEL[m] for m in available]}]}
        return name, method, None

    # Método não informado: só há o que decidir se o cartão tem os dois.
    if len(available) == 1:
        return name, METHOD_FROM_LABEL[available[0]], None
    return None, None, {"status": "needs_method",
                        "message": "was %s credit or debit?" % name,
                        "suggestions": [{"name": name, "methods":
                                         [METHOD_FROM_LABEL[m] for m in available]}]}


def _do_register_card(args):
    created = []
    for card in args.get("cards") or []:
        name = str(card.get("name", "")).strip()
        method = str(card.get("method", "")).upper()
        if not name or method not in METHOD_TO_PROTO:
            continue
        response = call("RegisterCard", cards().RegisterCard,
                        expenses_pb2.RegisterCardRequest(
                            name=name, method=METHOD_TO_PROTO[method]))
        created.append({"message": response.message, "created": response.created})
    if not created:
        return {"status": "rejected", "message": "no valid card in the command"}
    return {"status": "ok", "message": "; ".join(c["message"] for c in created),
            "result": {"cards": created}}


def _do_register_expense(args, registered):
    # Quem calcula a data é o datetime, nunca o modelo: ele devolve um rótulo.
    # A conta vem antes da validação do cartão de propósito: se o cartão não
    # conferir, a data já resolvida vai junto no "pending", e a interface
    # completa o lançamento sem precisar interpretar "ontem" por conta própria.
    when = args.get("date") or period.transaction_date(
        args.get("date_label") or args.get("period") or "")

    name, method, problem = _resolve_card(
        args.get("card", ""), str(args.get("method", "")).upper() or "", registered)
    if problem:
        # O comando não é descartado: volta para a interface com o que falta e
        # as opções, para o usuário completar sem redigitar a frase.
        problem["pending"] = dict(args, date=when)
        return problem

    amount = float(args.get("amount") or 0)
    if amount <= 0:
        return {"status": "rejected", "message": "amount must be greater than zero"}

    response = call("RegisterExpense", expenses().RegisterExpense,
                    expenses_pb2.RegisterExpenseRequest(
                        product=str(args.get("product") or "expense"),
                        description=str(args.get("description") or ""),
                        amount=amount, card=name,
                        method=METHOD_TO_PROTO[method],
                        category=str(args.get("category") or "other"),
                        date=when))
    if not response.ok:
        return {"status": "rejected", "message": response.message}
    return {"status": "ok", "message": response.message,
            "result": {"expense": expense_json(response.expense)}}


def _nlu_filter(args):
    """Filtro do protobuf a partir dos args do modelo, com o período resolvido."""
    start, end = period.resolve(args.get("period") or "")
    method = str(args.get("method", "")).upper()
    category = str(args.get("category", ""))
    return expenses_pb2.Filter(
        card=str(args.get("card", "")),
        method=METHOD_TO_PROTO.get(method, 0),
        category=category if category in get_args(Category) else "",
        start_date=start, end_date=end)


@api.post("/nlu/interpret")
def interpret_command(body: CommandIn):
    """Interpreta o texto e executa o comando, pelos mesmos RPCs das rotas acima."""
    started = time.monotonic()
    registered = _labeled_cards()
    command, interpreter, fallback = _interpret(body.text, registered)
    action = command.get("action", "unknown")
    args = command.get("args") or {}
    log.info("%-16s %-18s %r", "NLU", action, body.text)

    if action == "register_card":
        outcome = _do_register_card(args)
    elif action == "list_cards":
        outcome = {"status": "ok", "message": "%d cards" % len(registered),
                   "result": {"cards": [{"name": n, "methods":
                                         [METHOD_FROM_LABEL[m] for m in ms]}
                                        for n, ms in registered]}}
    elif action == "register_expense":
        outcome = _do_register_expense(args, registered)
    elif action == "search_expenses":
        filters = _nlu_filter(args)
        found = call("SearchExpenses", expenses().SearchExpenses, filters, stream=True)
        outcome = {"status": "ok", "message": "%d expenses" % len(found),
                   "result": {"expenses": [expense_json(e) for e in found],
                              "filter": _filter_json(filters)}}
    elif action == "summary":
        group_by = args.get("group_by") if args.get("group_by") in (
            "category", "card", "method") else "category"
        filters = _nlu_filter(args)
        response = call("SummaryByGroup", expenses().SummaryByGroup,
                        expenses_pb2.SummaryRequest(group_by=group_by, filter=filters))
        outcome = {"status": "ok", "message": "total %.2f" % response.grand_total,
                   "result": {"group_by": group_by,
                              "totals": [{"key": t.key, "total": t.total,
                                          "count": t.count} for t in response.totals],
                              "grand_total": response.grand_total,
                              "filter": _filter_json(filters)}}
    else:
        outcome = {"status": "unknown",
                   "message": args.get("reason") or "command not understood"}

    return dict(outcome, action=action, args=args, interpreter=interpreter,
                model=nlu.model_name() if interpreter == "claude" else None,
                fallback_reason=fallback,
                elapsed_ms=int((time.monotonic() - started) * 1000))


def _filter_json(filters):
    """O filtro que de fato foi para o protobuf — a interface exibe ao usuário."""
    return {"card": filters.card or None,
            "method": METHOD_FROM_PROTO.get(filters.method),
            "category": filters.category or None,
            "start_date": filters.start_date or None,
            "end_date": filters.end_date or None}


app.include_router(api)
