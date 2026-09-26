#!/usr/bin/env bash
# Sobe o backend inteiro na sua máquina: os dois microsserviços gRPC e o
# Gateway. Ctrl+C derruba os três.
#
# Usa SQLite em data/, nunca o Cloud SQL: as variáveis PG* do .env ficam de
# fora de propósito, porque o IP privado do banco não é alcançável daqui.
#
#   bash run_backend.sh
#   # em outro terminal, a interface web:
#   cd web && npm run dev          # http://localhost:5173
#   # ou, para quem prefere o terminal:
#   .venv/bin/python client/client.py
set -euo pipefail
cd "$(dirname "$0")"

# Só o que o Gateway precisa: segredo do JWT, o usuário de login e, se houver,
# a chave da LLM — é ele quem interpreta o texto vindo da interface web. (Um
# laço de read em vez de `source <(...)`: o bash 3.2 do macOS lê vazio nesse
# caso.)
if [ -f .env ]; then
  while IFS= read -r line; do
    export "$line"
  done < <(grep -E '^(JWT_SECRET|GATEWAY_USER|GATEWAY_PASSWORD|ANTHROPIC_[A-Z_]*)=' .env)
fi
unset PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

PY="$PWD/.venv/bin/python"
trap 'kill 0' EXIT   # ao sair, mata todos os processos filhos deste script

# --database relativo a server/, para os arquivos caírem em data/ na raiz do
# repositório — o mesmo lugar que as units do systemd usam na VM.
(cd server && "$PY" cards_service.py --database ../data/cards.db) &
(cd server && "$PY" expenses_service.py --database ../data/expenses.db) &
(cd gateway && "$PY" -m uvicorn app:app --host 127.0.0.1 --port 8000) &

wait
