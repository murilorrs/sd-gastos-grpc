#!/usr/bin/env python3
"""Verificação executável do Microsserviço B.

Sobe o servidor gRPC numa porta efêmera com um banco em memória e exercita os
seis RPCs através de um canal de verdade — ou seja, testa a serialização e o
transporte, não só as funções Python.

    python server/test_server.py
"""

import grpc

import expenses_pb2
import expenses_pb2_grpc
from server import create_server


def run():
    server, port = create_server(":memory:", "localhost:0")
    server.start()
    channel = grpc.insecure_channel("localhost:%d" % port)
    stub = expenses_pb2_grpc.ExpenseServiceStub(channel)
    try:
        check(stub)
    finally:
        channel.close()
        server.stop(grace=None)


def check(stub):
    # --- cards -------------------------------------------------------------
    stub.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="Nubank", method=expenses_pb2.CREDIT))
    stub.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="Nubank", method=expenses_pb2.DEBIT))
    stub.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="Itau", method=expenses_pb2.DEBIT))

    cards = stub.ListCards(expenses_pb2.ListCardsRequest()).cards
    assert [c.name for c in cards] == ["Itau", "Nubank"], cards
    assert list(cards[1].methods) == [expenses_pb2.CREDIT, expenses_pb2.DEBIT]

    # Cadastrar de novo não duplica: (name, method) é chave primária.
    stub.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="nubank", method=expenses_pb2.CREDIT))
    assert len(stub.ListCards(expenses_pb2.ListCardsRequest()).cards) == 2

    # --- validation --------------------------------------------------------
    ok = stub.ValidateCard(expenses_pb2.ValidateCardRequest(
        name="Nubank", method=expenses_pb2.CREDIT))
    assert ok.exists

    # O Itau existe, mas não no crédito.
    partial = stub.ValidateCard(expenses_pb2.ValidateCardRequest(
        name="Itau", method=expenses_pb2.CREDIT))
    assert not partial.exists and "not for credit" in partial.message, partial.message

    # Erro de digitação: deve sugerir o cartão real.
    typo = stub.ValidateCard(expenses_pb2.ValidateCardRequest(name="Nubanck"))
    assert not typo.exists
    assert "Nubank" in [c.name for c in typo.suggestions], typo.suggestions

    # --- recording expenses ------------------------------------------------
    response = stub.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="mechanical keyboard", amount=89.0, card="Nubank",
        method=expenses_pb2.CREDIT, category="technology", date="2026-09-05"))
    assert response.ok and response.expense.id == 1, response

    stub.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="lunch", amount=42.0, card="Itau",
        method=expenses_pb2.DEBIT, category="food", date="2026-09-08"))
    stub.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="ride", amount=23.0, card="Nubank",
        method=expenses_pb2.DEBIT, category="transport", date="2026-08-20"))

    # Cartão inexistente: a chave estrangeira barra mesmo sem validação prévia.
    refused = stub.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="pizza", amount=50.0, card="Bradesco",
        method=expenses_pb2.CREDIT, category="food"))
    assert not refused.ok, "expense on unknown card should be refused"

    # Valor inválido vira INVALID_ARGUMENT, não um registro zerado.
    try:
        stub.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
            product="nothing", amount=0, card="Nubank",
            method=expenses_pb2.CREDIT))
        raise AssertionError("zero amount should have been refused")
    except grpc.RpcError as error:
        assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, error.code()

    # --- search (streaming) ------------------------------------------------
    everything = list(stub.SearchExpenses(expenses_pb2.Filter()))
    assert len(everything) == 3, everything

    nubank_credit = list(stub.SearchExpenses(expenses_pb2.Filter(
        card="Nubank", method=expenses_pb2.CREDIT)))
    assert [e.product for e in nubank_credit] == ["mechanical keyboard"]

    # Filtro por intervalo de datas: só setembro.
    september = list(stub.SearchExpenses(expenses_pb2.Filter(
        start_date="2026-09-01", end_date="2026-09-30")))
    assert len(september) == 2, [e.date for e in september]

    # Combinado: Nubank + débito + agosto.
    combined = list(stub.SearchExpenses(expenses_pb2.Filter(
        card="Nubank", method=expenses_pb2.DEBIT,
        start_date="2026-08-01", end_date="2026-08-31")))
    assert [e.product for e in combined] == ["ride"], combined

    # --- summary -----------------------------------------------------------
    by_category = stub.SummaryByGroup(expenses_pb2.SummaryRequest(
        group_by="category"))
    assert abs(by_category.grand_total - 154.0) < 0.001, by_category.grand_total
    assert by_category.totals[0].key == "technology"  # ordenado por total

    by_method = stub.SummaryByGroup(expenses_pb2.SummaryRequest(group_by="method"))
    keys = {t.key: t.total for t in by_method.totals}
    assert keys == {"credit": 89.0, "debit": 65.0}, keys

    # O resumo respeita o filtro.
    filtered = stub.SummaryByGroup(expenses_pb2.SummaryRequest(
        group_by="card", filter=expenses_pb2.Filter(method=expenses_pb2.DEBIT)))
    assert abs(filtered.grand_total - 65.0) < 0.001, filtered.grand_total

    # group_by fora da lista fechada é recusado — sem isso seria injeção de SQL.
    for invalid in ("expenses; DROP TABLE expenses", "amount", ""):
        try:
            stub.SummaryByGroup(expenses_pb2.SummaryRequest(group_by=invalid))
            raise AssertionError("group_by=%r should have been refused" % invalid)
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, error.code()

    # O DROP TABLE não passou: os dados continuam lá.
    assert len(list(stub.SearchExpenses(expenses_pb2.Filter()))) == 3


if __name__ == "__main__":
    run()
    print("all checks passed")
