-- Esquema do banco, para quem preferir criá-lo pelo Cloud SQL Studio em vez de
-- deixar os serviços criarem na primeira subida.
--
-- Os microsserviços rodam estes CREATE TABLE IF NOT EXISTS sozinhos ao
-- iniciar, então este arquivo é opcional. Ele existe para o caso de o usuário
-- do banco não ter permissão de DDL, e para deixar o esquema à vista.
--
-- Cada microsserviço é dono de uma tabela. Não há chave estrangeira entre elas
-- de propósito: ela acoplaria os dois serviços por baixo do contrato gRPC.
-- Quem garante que o cartão existe é a chamada ValidateCard.

CREATE TABLE IF NOT EXISTS cards (
    name   TEXT    NOT NULL,
    method INTEGER NOT NULL,          -- 1 = CREDIT, 2 = DEBIT (enum do .proto)
    PRIMARY KEY (name, method)
);

CREATE TABLE IF NOT EXISTS expenses (
    id          SERIAL PRIMARY KEY,
    product     TEXT             NOT NULL,
    description TEXT             NOT NULL DEFAULT '',
    amount      DOUBLE PRECISION NOT NULL,
    card        TEXT             NOT NULL,
    method      INTEGER          NOT NULL,
    category    TEXT             NOT NULL,
    date        TEXT             NOT NULL,   -- AAAA-MM-DD
    created_at  TEXT             NOT NULL
);

-- As consultas da tela filtram por data e agrupam por categoria, cartão e
-- método. Estes índices cobrem os filtros mais usados.
CREATE INDEX IF NOT EXISTS expenses_date_idx     ON expenses (date);
CREATE INDEX IF NOT EXISTS expenses_card_idx     ON expenses (LOWER(card));
CREATE INDEX IF NOT EXISTS expenses_category_idx ON expenses (category);

-- Permissões do usuário da aplicação, se ele não for o dono do banco:
--   GRANT SELECT, INSERT, UPDATE, DELETE ON cards, expenses TO expenses_app;
--   GRANT USAGE, SELECT ON SEQUENCE expenses_id_seq TO expenses_app;
