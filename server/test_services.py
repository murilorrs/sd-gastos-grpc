#!/usr/bin/env python3
"""Verificação executável dos dois microsserviços.

Sobe o serviço de Cartões e o de Gastos em portas efêmeras, com bancos em
memória, e os exercita por canais gRPC de verdade — inclusive a chamada que o
serviço de Gastos faz ao de Cartões antes de gravar. Testa serialização e
transporte, não só as funções Python.

    python server/test_services.py
"""

import grpc

import cards_service
import expenses_pb2
import expenses_pb2_grpc
import expenses_service


def start_services():
    """Sobe os dois serviços.

    Devolve (stub de cartões, stub de gastos, parar, servidor de cartões,
    endereços {"cards": ..., "expenses": ...}).
    """
    cards_server, cards_port = cards_service.create_server(":memory:", "localhost:0")
    cards_server.start()
    expenses_server, expenses_port = expenses_service.create_server(
        ":memory:", "localhost:0", cards_address="localhost:%d" % cards_port)
    expenses_server.start()

    cards_channel = grpc.insecure_channel("localhost:%d" % cards_port)
    expenses_channel = grpc.insecure_channel("localhost:%d" % expenses_port)

    def stop():
        cards_channel.close()
        expenses_channel.close()
        expenses_server.stop(grace=None)
        cards_server.stop(grace=None)

    return (expenses_pb2_grpc.CardServiceStub(cards_channel),
            expenses_pb2_grpc.ExpenseServiceStub(expenses_channel),
            stop, cards_server,
            {"cards": "localhost:%d" % cards_port,
             "expenses": "localhost:%d" % expenses_port})


def run():
    cards, expenses, stop, _, _ = start_services()
    try:
        check(cards, expenses)
    finally:
        stop()
    check_cards_down()


def check(cards, expenses):
    # --- cards -------------------------------------------------------------
    created = cards.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="Nubank", method=expenses_pb2.CREDIT))
    assert created.created
    cards.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="Nubank", method=expenses_pb2.DEBIT))
    cards.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="Itau", method=expenses_pb2.DEBIT))

    listed = cards.ListCards(expenses_pb2.ListCardsRequest()).cards
    assert [c.name for c in listed] == ["Itau", "Nubank"], listed
    assert list(listed[1].methods) == [expenses_pb2.CREDIT, expenses_pb2.DEBIT]

    # Cadastrar de novo, em outra grafia, não duplica e não é criação.
    again = cards.RegisterCard(expenses_pb2.RegisterCardRequest(
        name="nubank", method=expenses_pb2.CREDIT))
    assert not again.created and "Nubank" in again.message, again
    assert len(cards.ListCards(expenses_pb2.ListCardsRequest()).cards) == 2

    # --- validation --------------------------------------------------------
    ok = cards.ValidateCard(expenses_pb2.ValidateCardRequest(
        name="NUBANK", method=expenses_pb2.CREDIT))
    assert ok.exists and ok.name == "Nubank", ok   # devolve a grafia cadastrada

    partial = cards.ValidateCard(expenses_pb2.ValidateCardRequest(
        name="Itau", method=expenses_pb2.CREDIT))
    assert not partial.exists and "not for credit" in partial.message, partial.message

    typo = cards.ValidateCard(expenses_pb2.ValidateCardRequest(name="Nubanck"))
    assert not typo.exists
    assert "Nubank" in [c.name for c in typo.suggestions], typo.suggestions

    # --- recording expenses (Gastos chama Cartões via gRPC) -----------------
    response = expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="mechanical keyboard", amount=89.0, card="nubank",
        method=expenses_pb2.CREDIT, category="technology", date="2026-09-05"))
    assert response.ok and response.expense.id == 1, response
    # Gravou com a grafia que o serviço de Cartões devolveu, não a digitada.
    assert response.expense.card == "Nubank", response.expense.card

    expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="lunch", amount=42.0, card="Itau",
        method=expenses_pb2.DEBIT, category="food", date="2026-09-08"))
    expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="ride", amount=23.0, card="Nubank",
        method=expenses_pb2.DEBIT, category="transport", date="2026-08-20"))

    # Cartão inexistente: o serviço de Cartões diz que não, e nada é gravado.
    refused = expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="pizza", amount=50.0, card="Bradesco",
        method=expenses_pb2.CREDIT, category="food"))
    assert not refused.ok and "Bradesco" in refused.message, refused

    # Cartão que existe, mas não naquele método: também recusado.
    wrong_method = expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
        product="pizza", amount=50.0, card="Itau",
        method=expenses_pb2.CREDIT, category="food"))
    assert not wrong_method.ok, wrong_method

    # Valor inválido vira INVALID_ARGUMENT, não um registro zerado.
    try:
        expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
            product="nothing", amount=0, card="Nubank",
            method=expenses_pb2.CREDIT))
        raise AssertionError("zero amount should have been refused")
    except grpc.RpcError as error:
        assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, error.code()

    # --- search (streaming) ------------------------------------------------
    everything = list(expenses.SearchExpenses(expenses_pb2.Filter()))
    assert len(everything) == 3, everything

    nubank_credit = list(expenses.SearchExpenses(expenses_pb2.Filter(
        card="NUBANK", method=expenses_pb2.CREDIT)))
    assert [e.product for e in nubank_credit] == ["mechanical keyboard"]

    september = list(expenses.SearchExpenses(expenses_pb2.Filter(
        start_date="2026-09-01", end_date="2026-09-30")))
    assert len(september) == 2, [e.date for e in september]

    combined = list(expenses.SearchExpenses(expenses_pb2.Filter(
        card="Nubank", method=expenses_pb2.DEBIT,
        start_date="2026-08-01", end_date="2026-08-31")))
    assert [e.product for e in combined] == ["ride"], combined

    # --- summary -----------------------------------------------------------
    by_category = expenses.SummaryByGroup(expenses_pb2.SummaryRequest(
        group_by="category"))
    assert abs(by_category.grand_total - 154.0) < 0.001, by_category.grand_total
    assert by_category.totals[0].key == "technology"  # ordenado por total

    by_method = expenses.SummaryByGroup(expenses_pb2.SummaryRequest(group_by="method"))
    keys = {t.key: t.total for t in by_method.totals}
    assert keys == {"credit": 89.0, "debit": 65.0}, keys

    filtered = expenses.SummaryByGroup(expenses_pb2.SummaryRequest(
        group_by="card", filter=expenses_pb2.Filter(method=expenses_pb2.DEBIT)))
    assert abs(filtered.grand_total - 65.0) < 0.001, filtered.grand_total

    # group_by fora da lista fechada é recusado — sem isso seria injeção de SQL.
    for invalid in ("expenses; DROP TABLE expenses", "amount", ""):
        try:
            expenses.SummaryByGroup(expenses_pb2.SummaryRequest(group_by=invalid))
            raise AssertionError("group_by=%r should have been refused" % invalid)
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, error.code()

    # O DROP TABLE não passou: os dados continuam lá.
    assert len(list(expenses.SearchExpenses(expenses_pb2.Filter()))) == 3


def check_cards_down():
    """Com o serviço de Cartões fora do ar, Gastos recusa em vez de gravar às cegas."""
    cards, expenses, stop, cards_server, _ = start_services()
    try:
        cards_server.stop(grace=None)
        try:
            expenses.RegisterExpense(expenses_pb2.RegisterExpenseRequest(
                product="coffee", amount=5.0, card="Nubank",
                method=expenses_pb2.CREDIT))
            raise AssertionError("expense recorded without the cards service")
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.UNAVAILABLE, error.code()
        assert list(expenses.SearchExpenses(expenses_pb2.Filter())) == []
    finally:
        stop()


if __name__ == "__main__":
    run()
    print("all checks passed")
