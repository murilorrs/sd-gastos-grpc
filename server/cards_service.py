#!/usr/bin/env python3
"""Microsserviço de Cartões — dono da tabela de cartões.

Responde a quem precisar saber que cartões existem: o Gateway (para o usuário
cadastrar, listar e corrigir cartões) e o microsserviço de Gastos (que pergunta
aqui antes de gravar qualquer gasto).
"""

import grpc

import expenses_pb2
import expenses_pb2_grpc
from common import METHOD_LABEL, log_rpc, new_server, serve
from database import CardStore

DEFAULT_PORT = 50052


class CardService(expenses_pb2_grpc.CardServiceServicer):
    def __init__(self, store):
        self._store = store

    def RegisterCard(self, request, context):
        log_rpc(context, "RegisterCard", "%s / %s" % (
            request.name, METHOD_LABEL[request.method]))
        name = request.name.strip()
        if not name:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "card name is required")
        if request.method == expenses_pb2.METHOD_UNSPECIFIED:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          "payment method is required: CREDIT or DEBIT")

        created = self._store.register_card(name, request.method)
        label = "%s (%s)" % (self._store.canonical_name(name),
                             METHOD_LABEL[request.method])
        return expenses_pb2.RegisterCardResponse(
            ok=True,
            created=created,
            message="%s registered" % label if created
            else "%s was already registered" % label,
        )

    def ListCards(self, request, context):
        log_rpc(context, "ListCards", "")
        return expenses_pb2.ListCardsResponse(
            cards=[expenses_pb2.Card(name=name, methods=methods)
                   for name, methods in self._store.list_cards()]
        )

    def ValidateCard(self, request, context):
        """A checagem que impede um cartão inventado de virar uma operação."""
        log_rpc(context, "ValidateCard", "%s / %s" % (
            request.name, METHOD_LABEL[request.method]))
        typed = request.name.strip()
        name = self._store.canonical_name(typed)

        if name and self._store.card_exists(name, request.method):
            return expenses_pb2.ValidateCardResponse(
                exists=True,
                name=name,
                message="%s (%s) is registered" % (name, METHOD_LABEL[request.method]),
            )

        # O nome existe, mas não naquele método: mensagem mais útil que "not found".
        if name and request.method:
            methods = dict(self._store.list_cards())[name]
            return expenses_pb2.ValidateCardResponse(
                exists=False,
                name=name,
                message="card %s is registered, but not for %s (only: %s)" % (
                    name, METHOD_LABEL[request.method],
                    ", ".join(METHOD_LABEL[m] for m in methods)),
                suggestions=[expenses_pb2.Card(name=name, methods=methods)],
            )

        suggestions = self._store.suggest_cards(typed) or self._store.list_cards()
        if suggestions:
            extra = "; registered: " + ", ".join(n for n, _ in suggestions)
        else:
            extra = "; no cards registered yet"
        return expenses_pb2.ValidateCardResponse(
            exists=False,
            message="card %s not found%s" % (typed, extra),
            suggestions=[expenses_pb2.Card(name=n, methods=m) for n, m in suggestions],
        )


def create_server(db_path="data/cards.db", address="127.0.0.1:%d" % DEFAULT_PORT):
    """Devolve (server, port). db_path=None usa PostgreSQL; a porta 0 é para testes."""
    server = new_server()
    expenses_pb2_grpc.add_CardServiceServicer_to_server(
        CardService(CardStore(db_path)), server)
    port = server.add_insecure_port(address)
    return server, port


if __name__ == "__main__":
    serve("cards service", create_server, DEFAULT_PORT, "data/cards.db")
