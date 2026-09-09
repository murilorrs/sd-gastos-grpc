#!/usr/bin/env python3
"""Microsserviço B — servidor gRPC.

Não conhece a LLM. Recebe mensagens já estruturadas segundo proto/expenses.proto,
valida, persiste no SQLite e responde. Se amanhã o cliente trocar o Gemini por
outro modelo, ou por um formulário web, nada aqui muda.
"""

import argparse
import logging
import sqlite3
from concurrent import futures

import grpc

import expenses_pb2
import expenses_pb2_grpc
from database import Database, today

METHOD_LABEL = {
    expenses_pb2.METHOD_UNSPECIFIED: "any",
    expenses_pb2.CREDIT: "credit",
    expenses_pb2.DEBIT: "debit",
}

log = logging.getLogger("server")


class ExpenseService(expenses_pb2_grpc.ExpenseServiceServicer):
    def __init__(self, database):
        self._db = database

    # ---------- cards ----------

    def RegisterCard(self, request, context):
        _log_rpc(context, "RegisterCard", "%s / %s" % (
            request.name, METHOD_LABEL[request.method]))
        name = request.name.strip()
        if not name:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "card name is required")
        if request.method == expenses_pb2.METHOD_UNSPECIFIED:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "payment method is required: CREDIT or DEBIT")

        created = self._db.register_card(name, request.method)
        label = "%s (%s)" % (name, METHOD_LABEL[request.method])
        return expenses_pb2.RegisterCardResponse(
            ok=True,
            message="%s registered" % label if created
            else "%s was already registered" % label,
        )

    def ListCards(self, request, context):
        _log_rpc(context, "ListCards", "")
        return expenses_pb2.ListCardsResponse(
            cards=[expenses_pb2.Card(name=name, methods=methods)
                   for name, methods in self._db.list_cards()]
        )

    def ValidateCard(self, request, context):
        """A checagem que impede um cartão inventado de virar uma operação."""
        _log_rpc(context, "ValidateCard", "%s / %s" % (
            request.name, METHOD_LABEL[request.method]))
        name = request.name.strip()

        if self._db.card_exists(name, request.method):
            return expenses_pb2.ValidateCardResponse(
                exists=True,
                message="%s (%s) is registered" % (
                    name, METHOD_LABEL[request.method]),
            )

        # O nome existe, mas não naquele método: mensagem mais útil que "not found".
        if request.method and self._db.card_exists(name):
            methods = dict(self._db.list_cards())[name]
            return expenses_pb2.ValidateCardResponse(
                exists=False,
                message="card %s is registered, but not for %s (only: %s)" % (
                    name, METHOD_LABEL[request.method],
                    ", ".join(METHOD_LABEL[m] for m in methods)),
                suggestions=[expenses_pb2.Card(name=name, methods=methods)],
            )

        suggestions = self._db.suggest_cards(name) or self._db.list_cards()
        if suggestions:
            extra = "; registered: " + ", ".join(n for n, _ in suggestions)
        else:
            extra = "; no cards registered yet"
        return expenses_pb2.ValidateCardResponse(
            exists=False,
            message="card %s not found%s" % (name, extra),
            suggestions=[expenses_pb2.Card(name=n, methods=m)
                         for n, m in suggestions],
        )

    # ---------- expenses ----------

    def RegisterExpense(self, request, context):
        _log_rpc(context, "RegisterExpense", "%s %.2f %s/%s" % (
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

        try:
            expense = self._db.insert_expense(
                product=request.product.strip(),
                description=request.description.strip(),
                amount=request.amount,
                card=request.card.strip(),
                method=request.method,
                category=(request.category.strip() or "other"),
                date=(request.date.strip() or today()),
            )
        except sqlite3.IntegrityError:
            return expenses_pb2.RegisterExpenseResponse(
                ok=False,
                message="card %s for %s is not registered" % (
                    request.card, METHOD_LABEL[request.method]),
            )

        return expenses_pb2.RegisterExpenseResponse(
            ok=True,
            expense=expenses_pb2.Expense(**expense),
            message="expense #%d recorded" % expense["id"],
        )

    def SearchExpenses(self, request, context):
        _log_rpc(context, "SearchExpenses", _describe_filter(request))
        for expense in self._db.search_expenses(_filter_dict(request)):
            yield expenses_pb2.Expense(**expense)

    def SummaryByGroup(self, request, context):
        _log_rpc(context, "SummaryByGroup", "by %s %s" % (
            request.group_by, _describe_filter(request.filter)))
        try:
            totals, grand_total = self._db.summary(
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


def _log_rpc(context, method, detail):
    """O log que prova a comunicação durante a apresentação."""
    log.info("%-16s from %-24s %s", method, context.peer(), detail)


def create_server(db_path="expenses.db", address="0.0.0.0:50051"):
    """Devolve (server, port). A porta importa nos testes, que usam a 0."""
    database = Database(db_path)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    expenses_pb2_grpc.add_ExpenseServiceServicer_to_server(
        ExpenseService(database), server)
    port = server.add_insecure_port(address)
    return server, port


def main():
    parser = argparse.ArgumentParser(description="Microservice B - gRPC server")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--database", default="expenses.db")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    server, port = create_server(args.database, "0.0.0.0:%d" % args.port)
    server.start()
    log.info("gRPC server listening on 0.0.0.0:%d (database: %s)",
             port, args.database)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        log.info("shutting down")
        server.stop(grace=1)


if __name__ == "__main__":
    main()
