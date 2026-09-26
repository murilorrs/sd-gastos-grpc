#!/usr/bin/env python3
"""Microsserviço de Gastos — dono da tabela de gastos.

Não conhece a tabela de cartões. Antes de gravar um gasto, pergunta ao
microsserviço de Cartões, via gRPC, se o cartão existe naquele método. É a
comunicação entre microsserviços do sistema: se Cartões estiver fora do ar,
Gastos recusa o registro em vez de gravar um gasto que ninguém conferiu.
"""

import os

import grpc

import expenses_pb2
import expenses_pb2_grpc
from common import METHOD_LABEL, log_rpc, new_server, serve
from database import ExpenseStore, today

DEFAULT_PORT = 50051


class ExpenseService(expenses_pb2_grpc.ExpenseServiceServicer):
    def __init__(self, store, cards):
        self._store = store
        self._cards = cards   # stub do CardService

    def RegisterExpense(self, request, context):
        log_rpc(context, "RegisterExpense", "%s %.2f %s/%s" % (
            request.product, request.amount, request.card,
            METHOD_LABEL[request.method]))

        if not request.product.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "product is required")
        if request.amount <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "amount must be greater than zero")
        if request.method == expenses_pb2.METHOD_UNSPECIFIED:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "payment method is required: CREDIT or DEBIT")

        validation = self._validate_card(request.card, request.method, context)
        if not validation.exists:
            return expenses_pb2.RegisterExpenseResponse(ok=False,
                                                        message=validation.message)

        expense = self._store.insert_expense(
            product=request.product.strip(),
            description=request.description.strip(),
            amount=request.amount,
            card=validation.name,   # grafia cadastrada, não a digitada
            method=request.method,
            category=(request.category.strip() or "other"),
            date=(request.date.strip() or today()),
        )
        return expenses_pb2.RegisterExpenseResponse(
            ok=True,
            expense=expenses_pb2.Expense(**expense),
            message="expense #%d recorded" % expense["id"],
        )

    def _validate_card(self, card, method, context):
        """Pergunta ao microsserviço de Cartões se o par (cartão, método) existe.

        É a comunicação entre microsserviços do sistema, e o mesmo passo vale
        para criar e para alterar: uma edição pode trocar o cartão tanto quanto
        uma criação pode inventá-lo. Se o serviço de Cartões estiver fora do ar,
        aborta — gravar às cegas é pior que recusar.
        """
        try:
            return self._cards.ValidateCard(
                expenses_pb2.ValidateCardRequest(name=card.strip(), method=method),
                timeout=5,
            )
        except grpc.RpcError as error:
            context.abort(grpc.StatusCode.UNAVAILABLE,
                          "cards service unavailable: %s" % error.code().name)

    def UpdateExpense(self, request, context):
        """Regrava um gasto existente. Mesmas checagens do registro, mais o id."""
        log_rpc(context, "UpdateExpense", "#%d %s %.2f %s/%s" % (
            request.id, request.product, request.amount, request.card,
            METHOD_LABEL[request.method]))

        if request.id <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "expense id is required")
        if not request.product.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "product is required")
        if request.amount <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "amount must be greater than zero")
        if request.method == expenses_pb2.METHOD_UNSPECIFIED:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "payment method is required: CREDIT or DEBIT")

        current = self._store.get_expense(request.id)
        if current is None:
            context.abort(grpc.StatusCode.NOT_FOUND,
                          "expense #%d not found" % request.id)

        validation = self._validate_card(request.card, request.method, context)
        if not validation.exists:
            return expenses_pb2.RegisterExpenseResponse(ok=False,
                                                        message=validation.message)

        expense = self._store.update_expense(
            request.id,
            product=request.product.strip(),
            description=request.description.strip(),
            amount=request.amount,
            card=validation.name,   # grafia cadastrada, não a digitada
            method=request.method,
            category=(request.category.strip() or current["category"]),
            date=(request.date.strip() or current["date"]),
        )
        # Só acontece se alguém remover o gasto entre o get e o update acima.
        if expense is None:
            context.abort(grpc.StatusCode.NOT_FOUND,
                          "expense #%d not found" % request.id)

        return expenses_pb2.RegisterExpenseResponse(
            ok=True,
            expense=expenses_pb2.Expense(**expense),
            message="expense #%d updated" % expense["id"],
        )

    def DeleteExpense(self, request, context):
        log_rpc(context, "DeleteExpense", "#%d" % request.id)
        if request.id <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "expense id is required")
        if not self._store.delete_expense(request.id):
            context.abort(grpc.StatusCode.NOT_FOUND,
                          "expense #%d not found" % request.id)
        return expenses_pb2.DeleteExpenseResponse(
            ok=True, message="expense #%d deleted" % request.id)

    def SearchExpenses(self, request, context):
        log_rpc(context, "SearchExpenses", _describe_filter(request))
        for expense in self._store.search_expenses(_filter_dict(request)):
            yield expenses_pb2.Expense(**expense)

    def SummaryByGroup(self, request, context):
        log_rpc(context, "SummaryByGroup", "by %s %s" % (
            request.group_by, _describe_filter(request.filter)))
        try:
            totals, grand_total = self._store.summary(
                request.group_by, _filter_dict(request.filter))
        except ValueError as error:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))

        # Ao agrupar por método a chave vem como inteiro do enum; traduz para
        # texto legível antes de devolver.
        def label(key):
            if request.group_by == "method":
                return METHOD_LABEL.get(key, str(key))
            return str(key)

        return expenses_pb2.SummaryResponse(
            totals=[expenses_pb2.GroupTotal(key=label(k), total=t, count=c)
                    for k, t, c in totals],
            grand_total=grand_total,
        )


def _filter_dict(filters):
    return {
        "card": filters.card.strip(),
        "method": filters.method,
        "category": filters.category.strip(),
        "start_date": filters.start_date.strip(),
        "end_date": filters.end_date.strip(),
    }


def _describe_filter(filters):
    parts = []
    if filters.card:
        parts.append("card=%s" % filters.card)
    if filters.method:
        parts.append("method=%s" % METHOD_LABEL[filters.method])
    if filters.category:
        parts.append("category=%s" % filters.category)
    if filters.start_date or filters.end_date:
        parts.append("range=%s..%s" % (
            filters.start_date or "-", filters.end_date or "-"))
    return " ".join(parts) or "no filter"


def create_server(db_path="data/expenses.db",
                  address="127.0.0.1:%d" % DEFAULT_PORT, cards_address=None):
    """Devolve (server, port). db_path=None usa PostgreSQL; a porta 0 é para testes."""
    cards_address = cards_address or os.environ.get("CARDS_ADDR", "localhost:50052")
    cards = expenses_pb2_grpc.CardServiceStub(grpc.insecure_channel(cards_address))
    server = new_server()
    expenses_pb2_grpc.add_ExpenseServiceServicer_to_server(
        ExpenseService(ExpenseStore(db_path), cards), server)
    port = server.add_insecure_port(address)
    return server, port


if __name__ == "__main__":
    serve("expenses service", create_server, DEFAULT_PORT, "data/expenses.db")
