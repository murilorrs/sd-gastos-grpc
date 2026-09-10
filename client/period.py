"""Converte rótulos de período em datas concretas.

O modelo devolve um rótulo ("this_month"); quem faz a conta é o datetime.
Modelos de linguagem erram aritmética de data com frequência — principalmente
virada de mês e de ano — e aqui o erro seria silencioso: a consulta traria o
intervalo errado sem nenhum aviso.
"""

from datetime import date, timedelta

# Rótulos aceitos, na ordem em que aparecem no prompt do modelo.
PERIOD_LABELS = (
    "today", "yesterday", "this_week", "this_month", "last_month",
    "this_year", "last_7_days", "last_30_days", "all_time",
)

# Rótulos válidos para a data de uma transação, com o deslocamento em dias.
_DAY_OFFSET = {"today": 0, "yesterday": 1, "day_before_yesterday": 2}


def _first_day(value):
    return value.replace(day=1)


def _last_day(value):
    """Último dia do mês de `value`, sem depender do módulo calendar."""
    next_month = date(value.year + (value.month == 12), value.month % 12 + 1, 1)
    return next_month - timedelta(days=1)


def resolve(label, today=None):
    """Rótulo -> (start_date, end_date) em YYYY-MM-DD.

    ("", "") significa sem restrição de data.
    """
    today = today or date.today()

    if label == "today":
        return today.isoformat(), today.isoformat()
    if label == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday.isoformat(), yesterday.isoformat()
    if label == "this_week":
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat(), today.isoformat()
    if label == "this_month":
        return _first_day(today).isoformat(), _last_day(today).isoformat()
    if label == "last_month":
        end = _first_day(today) - timedelta(days=1)
        return _first_day(end).isoformat(), end.isoformat()
    if label == "this_year":
        return date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()
    if label == "last_7_days":
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    if label == "last_30_days":
        return (today - timedelta(days=29)).isoformat(), today.isoformat()
    # "all_time", vazio ou rótulo desconhecido: sem filtro de data.
    return "", ""


def transaction_date(label, today=None):
    """Rótulo -> a data em que o gasto aconteceu (YYYY-MM-DD).

    O prompt pede rótulos de um único dia, mas o modelo às vezes devolve um de
    período ("paguei a farmácia mês passado" -> last_month). Cair para hoje
    nesse caso gravaria a data errada em silêncio, então o período vira o seu
    último dia — limitado a hoje, para nunca datar um gasto no futuro.
    """
    today = today or date.today()
    if not label or label in _DAY_OFFSET:
        return (today - timedelta(days=_DAY_OFFSET.get(label or "today", 0))).isoformat()

    _, end = resolve(label, today)
    if not end:
        return today.isoformat()
    return min(end, today.isoformat())


def _self_check():
    # Virada de ano e de mês são os casos onde o modelo erraria.
    assert resolve("this_month", date(2026, 12, 15)) == ("2026-12-01", "2026-12-31")
    assert resolve("last_month", date(2026, 1, 10)) == ("2025-12-01", "2025-12-31")
    assert resolve("last_month", date(2026, 3, 31)) == ("2026-02-01", "2026-02-28")
    assert resolve("this_month", date(2028, 2, 5)) == ("2028-02-01", "2028-02-29")
    # A semana começa na segunda; 2026-09-09 é uma quarta.
    assert resolve("this_week", date(2026, 9, 9)) == ("2026-09-07", "2026-09-09")
    assert resolve("last_7_days", date(2026, 9, 9)) == ("2026-09-03", "2026-09-09")
    assert resolve("all_time", date(2026, 9, 9)) == ("", "")
    assert resolve("", date(2026, 9, 9)) == ("", "")
    assert transaction_date("yesterday", date(2026, 1, 1)) == "2025-12-31"
    assert transaction_date(None, date(2026, 1, 1)) == "2026-01-01"
    # Rótulo de período num registro: último dia do período, nunca hoje por engano.
    assert transaction_date("last_month", date(2026, 9, 9)) == "2026-08-31"
    assert transaction_date("this_month", date(2026, 9, 9)) == "2026-09-09"
    assert transaction_date("this_year", date(2026, 9, 9)) == "2026-09-09"
    assert transaction_date("all_time", date(2026, 9, 9)) == "2026-09-09"
    print("period.py: all checks passed")


if __name__ == "__main__":
    _self_check()
