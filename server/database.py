"""Persistência do Microsserviço B: cartões e gastos em PostgreSQL ou SQLite.

Na nuvem o banco é um Cloud SQL (PostgreSQL) com IP privado; localmente e nos
testes é um SQLite, que não exige servidor nem rede. As consultas são as mesmas
nos dois — só o esquema da tabela e o driver mudam.

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

# A única diferença de esquema entre os dois bancos é a coluna de id
# autoincrementada. DOUBLE PRECISION vale nos dois (no SQLite vira REAL; no
# Postgres, REAL teria só precisão simples e 21.90 viraria 21.899999).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    name   TEXT NOT NULL,
    method INTEGER NOT NULL,
    PRIMARY KEY (name, method)
);
CREATE TABLE IF NOT EXISTS expenses (
    id          {id_column},
    product     TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    amount      DOUBLE PRECISION NOT NULL,
    card        TEXT NOT NULL,
    method      INTEGER NOT NULL,
    category    TEXT NOT NULL,
    date        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (card, method) REFERENCES cards (name, method)
)
"""


class IntegrityError(Exception):
    """Violação de chave estrangeira, qualquer que seja o banco por baixo."""


class Database:
    """Uma conexão compartilhada, protegida por lock.

    O servidor gRPC atende em várias threads (ThreadPoolExecutor). O lock
    serializa o acesso sem pool de conexões — o volume deste projeto não
    justifica um.

    path=None usa PostgreSQL, com a conexão lida das variáveis PGHOST, PGPORT,
    PGDATABASE, PGUSER e PGPASSWORD (a convenção padrão do libpq). Qualquer
    outro valor é o caminho de um arquivo SQLite (":memory:" nos testes).
    """

    def __init__(self, path="expenses.db"):
        self._lock = threading.Lock()
        self._path = path
        self._postgres = path is None
        self._connect()
        id_column = ("SERIAL PRIMARY KEY" if self._postgres
                     else "INTEGER PRIMARY KEY AUTOINCREMENT")
        with self._lock:
            for statement in _SCHEMA.format(id_column=id_column).split(";"):
                if statement.strip():
                    self._run(statement)

    def _connect(self):
        if self._postgres:
            import psycopg
            from psycopg.rows import dict_row
            # String vazia = tudo vem das variáveis PG* do ambiente.
            self._con = psycopg.connect("", autocommit=True, row_factory=dict_row)
        else:
            # isolation_level=None é autocommit, igual ao Postgres acima.
            self._con = sqlite3.connect(self._path, check_same_thread=False,
                                        isolation_level=None)
            self._con.row_factory = sqlite3.Row
            # Sem este PRAGMA o SQLite ignora chaves estrangeiras silenciosamente.
            self._con.execute("PRAGMA foreign_keys = ON")

    def close(self):
        self._con.close()

    def _run(self, sql, params=()):
        """Executa uma instrução e devolve o cursor. Chamar com o lock pego.

        As consultas usam `?` como marcador; o psycopg espera `%s`. Nenhuma
        consulta deste arquivo tem `?` literal, então a troca é segura.
        """
        if self._postgres:
            import psycopg
            sql = sql.replace("?", "%s")
            try:
                return self._con.execute(sql, params)
            except psycopg.errors.IntegrityError as error:
                raise IntegrityError(str(error)) from error
            except psycopg.OperationalError:
                # Conexão perdida (manutenção ou reinício do Cloud SQL). Sem
                # isto, toda chamada falharia até alguém reiniciar o servidor.
                self._connect()
                return self._con.execute(sql, params)
        try:
            return self._con.execute(sql, params)
        except sqlite3.IntegrityError as error:
            raise IntegrityError(str(error)) from error

    # ---------- cards ----------
    #
    # O nome do cartão é comparado sem diferenciar maiúsculas ("nubank" e
    # "Nubank" são o mesmo cartão). LOWER() nas duas pontas faz isso nos dois
    # bancos; a grafia gravada é a do primeiro cadastro.

    def _canonical_name(self, name):
        row = self._run(
            "SELECT name FROM cards WHERE LOWER(name) = LOWER(?) LIMIT 1", (name,)
        ).fetchone()
        return row["name"] if row else name

    def register_card(self, name, method):
        """Cadastra (nome, método). True se era novo, False se já existia."""
        with self._lock:
            name = self._canonical_name(name)
            cursor = self._run(
                "INSERT INTO cards (name, method) VALUES (?, ?)"
                " ON CONFLICT DO NOTHING",
                (name, method),
            )
            return cursor.rowcount > 0

    def list_cards(self):
        """[(name, [methods])], ordenado por nome."""
        with self._lock:
            rows = self._run(
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
                sql = "SELECT 1 FROM cards WHERE LOWER(name) = LOWER(?) AND method = ?"
                args = (name, method)
            else:
                sql = "SELECT 1 FROM cards WHERE LOWER(name) = LOWER(?)"
                args = (name,)
            return self._run(sql, args).fetchone() is not None

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

        Levanta IntegrityError se (card, method) não estiver cadastrado — é a
        chave estrangeira agindo como última barreira contra um cartão
        inventado pela LLM.
        """
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
        with self._lock:
            card = self._canonical_name(card)
            row = self._run(
                "INSERT INTO expenses"
                " (product, description, amount, card, method, category, date, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (product, description, amount, card, method, category, date,
                 created_at),
            ).fetchall()[0]   # fetchall encerra a instrução; fetchone deixaria
                              # o SQLite com a escrita em aberto
        return {
            "id": row["id"],
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
            rows = self._run(
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
            rows = self._run(
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
        clauses.append("LOWER(card) = LOWER(?)")
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
