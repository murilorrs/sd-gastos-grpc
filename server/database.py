"""Persistência do Microsserviço B: cartões e gastos num SQLite.

Esta camada não sabe nada de gRPC — recebe e devolve tipos Python. O server.py
é quem traduz para as mensagens do protobuf.
"""

import datetime
import difflib
import sqlite3
import threading

# Colunas pelas quais o SummaryByGroup pode agrupar. O valor entra numa cláusula
# GROUP BY, então precisa vir de uma lista fechada: concatenar entrada do usuário
# no SQL seria injeção.
VALID_GROUPS = ("category", "card", "method")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    name   TEXT COLLATE NOCASE NOT NULL,
    method INTEGER NOT NULL,
    PRIMARY KEY (name, method)
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product     TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    amount      REAL NOT NULL,
    card        TEXT COLLATE NOCASE NOT NULL,
    method      INTEGER NOT NULL,
    category    TEXT NOT NULL,
    date        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (card, method) REFERENCES cards (name, method)
);
"""


class Database:
    """Uma conexão SQLite compartilhada, protegida por lock.

    O servidor gRPC atende em várias threads (ThreadPoolExecutor), e uma conexão
    do sqlite3 não é thread-safe por padrão. O lock resolve isso sem pool de
    conexões — o volume deste projeto não justifica um.
    """

    def __init__(self, path="expenses.db"):
        self._lock = threading.Lock()
        self._con = sqlite3.connect(path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        # Sem este PRAGMA o SQLite ignora chaves estrangeiras silenciosamente.
        self._con.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._con.executescript(_SCHEMA)
            self._con.commit()

    def close(self):
        self._con.close()

    # ---------- cards ----------

    def register_card(self, name, method):
        """Cadastra (nome, método). True se era novo, False se já existia."""
        with self._lock:
            cursor = self._con.execute(
                "INSERT OR IGNORE INTO cards (name, method) VALUES (?, ?)",
                (name, method),
            )
            self._con.commit()
            return cursor.rowcount > 0

    def list_cards(self):
        """[(name, [methods])], ordenado por nome."""
        with self._lock:
            rows = self._con.execute(
                "SELECT name, method FROM cards ORDER BY name, method"
            ).fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row["name"], []).append(row["method"])
        return sorted(grouped.items())

    def card_exists(self, name, method=0):
        """method=0 verifica só o nome, ignorando crédito/débito."""
        with self._lock:
            if method:
                sql = "SELECT 1 FROM cards WHERE name = ? AND method = ?"
                args = (name, method)
            else:
                sql = "SELECT 1 FROM cards WHERE name = ?"
                args = (name,)
            return self._con.execute(sql, args).fetchone() is not None

    def suggest_cards(self, name, limit=3):
        """Cartões de nome parecido — cobre erro de digitação ("Nubanck")."""
        cards = self.list_cards()
        close = difflib.get_close_matches(
            name, [n for n, _ in cards], n=limit, cutoff=0.6
        )
        return [(n, m) for n, m in cards if n in close]

    # ---------- expenses ----------

    def insert_expense(self, product, description, amount, card, method,
                       category, date):
        """Insere e devolve o gasto completo (com id).

        Levanta sqlite3.IntegrityError se (card, method) não estiver cadastrado
        — é a chave estrangeira agindo como última barreira contra um cartão
        inventado pela LLM.
        """
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cursor = self._con.execute(
                "INSERT INTO expenses"
                " (product, description, amount, card, method, category, date, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (product, description, amount, card, method, category, date,
                 created_at),
            )
            self._con.commit()
            new_id = cursor.lastrowid
        return {
            "id": new_id,
            "product": product,
            "description": description,
            "amount": amount,
            "card": card,
            "method": method,
            "category": category,
            "date": date,
            "created_at": created_at,
        }

    def search_expenses(self, filters):
        where, params = _build_where(filters)
        with self._lock:
            rows = self._con.execute(
                "SELECT id, product, description, amount, card, method, category,"
                " date, created_at FROM expenses " + where
                + " ORDER BY date DESC, id DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self, group_by, filters):
        """[(key, total, count)] mais o total geral."""
        if group_by not in VALID_GROUPS:
            raise ValueError("group_by must be one of: " + ", ".join(VALID_GROUPS))
        where, params = _build_where(filters)
        # group_by só chega aqui depois da checagem acima, então a interpolação
        # é segura; os valores do filtro seguem parametrizados.
        with self._lock:
            rows = self._con.execute(
                "SELECT {0} AS key, SUM(amount) AS total, COUNT(*) AS count"
                " FROM expenses {1} GROUP BY {0} ORDER BY total DESC".format(
                    group_by, where
                ),
                params,
            ).fetchall()
        totals = [(r["key"], r["total"], r["count"]) for r in rows]
        return totals, sum(t for _, t, _ in totals)


def _build_where(filters):
    """Constrói o WHERE a partir de um dict. Campo ausente = sem restrição."""
    clauses, params = [], []
    if filters.get("card"):
        clauses.append("card = ?")
        params.append(filters["card"])
    if filters.get("method"):
        clauses.append("method = ?")
        params.append(filters["method"])
    if filters.get("category"):
        clauses.append("category = ?")
        params.append(filters["category"])
    if filters.get("start_date"):
        clauses.append("date >= ?")
        params.append(filters["start_date"])
    if filters.get("end_date"):
        clauses.append("date <= ?")
        params.append(filters["end_date"])
    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def today():
    return datetime.date.today().isoformat()
