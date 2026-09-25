#!/usr/bin/env python3
"""Verificação executável do Gateway, com os dois microsserviços de verdade.

Sobe Cartões e Gastos em portas efêmeras e chama o Gateway por HTTP (via
TestClient). Cobre os requisitos da borda: 401 sem token, 400 para JSON
inválido, 201 na criação, e a tradução JSON -> gRPC até o banco.

    python gateway/test_gateway.py
"""

import os
import sys

# Os microsserviços ficam em ../server; o teste os sobe no mesmo processo.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

os.environ.update(JWT_SECRET="test-secret-with-at-least-32-bytes!", GATEWAY_USER="demo",
                  GATEWAY_PASSWORD="demo-password")

from test_services import start_services  # noqa: E402


def run():
    _, _, stop, _, addresses = start_services()
    # O Gateway descobre os serviços pelo ambiente; aponta para as portas
    # efêmeras antes de importar o app.
    os.environ["CARDS_ADDR"] = addresses["cards"]
    os.environ["EXPENSES_ADDR"] = addresses["expenses"]
    try:
        check()
    finally:
        stop()


def check():
    from fastapi.testclient import TestClient
    import app as gateway

    client = TestClient(gateway.app)

    # --- autenticação ------------------------------------------------------
    assert client.get("/cards").status_code == 401                    # sem token
    assert client.get("/cards", headers={"Authorization": "Bearer lixo"}).status_code == 401
    assert client.post("/auth/token", json={"username": "demo",
                                            "password": "errada"}).status_code == 401
    login = client.post("/auth/token", json={"username": "demo",
                                             "password": "demo-password"})
    assert login.status_code == 200, login.text
    auth = {"Authorization": "Bearer " + login.json()["access_token"]}

    # Rota pública continua aberta.
    assert client.get("/health").status_code == 200

    # --- validação: 400, e nada chega aos serviços --------------------------
    bad = [
        {},                                                              # tudo ausente
        {"name": "Nubank"},                                              # sem método
        {"name": "   ", "method": "CREDIT"},                             # nome em branco
        {"name": "Nubank", "method": "PIX"},                             # método inválido
    ]
    for body in bad:
        response = client.post("/cards", json=body, headers=auth)
        assert response.status_code == 400, (body, response.status_code, response.text)

    response = client.post("/cards", content=b"{nao e json", headers=auth)
    assert response.status_code == 400, response.text

    # --- cartões: 201 ao criar, 200 quando já existia ----------------------
    assert client.post("/cards", json={"name": "Nubank", "method": "CREDIT"},
                       headers=auth).status_code == 201
    again = client.post("/cards", json={"name": "nubank", "method": "CREDIT"},
                        headers=auth)
    assert again.status_code == 200 and not again.json()["created"], again.text

    cards = client.get("/cards", headers=auth).json()["cards"]
    assert cards == [{"name": "Nubank", "methods": ["CREDIT"]}], cards

    valid = client.get("/cards/validate", params={"name": "NUBANK", "method": "CREDIT"},
                       headers=auth).json()
    assert valid["exists"] and valid["name"] == "Nubank", valid

    # --- gastos ------------------------------------------------------------
    expense = {"product": "teclado", "amount": 89.9, "card": "nubank",
               "method": "CREDIT", "category": "technology", "date": "2026-09-24"}
    created = client.post("/expenses", json=expense, headers=auth)
    assert created.status_code == 201, created.text
    assert created.json()["expense"]["card"] == "Nubank"

    for field, value in (("amount", 0), ("amount", -5), ("category", "hackeado"),
                         ("date", "24/09/2026"), ("product", "")):
        response = client.post("/expenses", json=dict(expense, **{field: value}),
                               headers=auth)
        assert response.status_code == 400, (field, value, response.text)

    # Cartão que não existe: validação de negócio, feita pelo serviço de Cartões.
    unknown = client.post("/expenses", json=dict(expense, card="Bradesco"), headers=auth)
    assert unknown.status_code == 400 and "Bradesco" in unknown.json()["detail"], unknown.text

    found = client.get("/expenses", params={"card": "nubank"}, headers=auth).json()
    assert [e["product"] for e in found["expenses"]] == ["teclado"], found

    summary = client.get("/expenses/summary", params={"group_by": "method"},
                         headers=auth).json()
    assert summary == {"totals": [{"key": "credit", "total": 89.9, "count": 1}],
                       "grand_total": 89.9}, summary

    assert client.get("/expenses/summary", params={"group_by": "amount"},
                      headers=auth).status_code == 400
    assert client.get("/expenses", params={"start_date": "ontem"},
                      headers=auth).status_code == 400


if __name__ == "__main__":
    run()
    print("all checks passed")
