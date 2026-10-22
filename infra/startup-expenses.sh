#!/usr/bin/env bash
# Script de inicialização da vm-expenses — cole no campo "Script de
# inicialização" ao criar a VM no Google Cloud Console.
#
# Sobe apenas o microsserviço de Gastos, na porta 50051. Ele chama o de
# Cartões por gRPC antes de gravar, então a vm-cards precisa estar no ar
# primeiro, e o IP dela vai no CARDS_ADDR abaixo.
set -euo pipefail

# --------------------------- CONFIGURAÇÃO ---------------------------------
REPO_URL="https://github.com/murilorrs/sd-gastos-grpc.git"
TARGET_DIR="/opt/sd-gastos-grpc"

# IP INTERNO da vm-cards, com a porta. Sem isto, nenhum gasto é gravado:
# o serviço recusa em vez de gravar sem conferir o cartão.
CARDS_ADDR="10.128.0.4:50052"

# PostgreSQL: o IP interno da vm-db.
PGHOST="10.128.0.3"
PGPORT="5432"
PGDATABASE="expenses"
PGUSER="expenses_app"
PGPASSWORD="TROQUE-PELA-SENHA-DO-BANCO"
# "prefer" usa TLS quando o servidor oferece e segue sem ele quando não —
# o container não tem certificado, e o tráfego não sai da VPC.
PGSSLMODE="prefer"

echo "==> pacotes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv git

echo "==> código"
mkdir -p "$TARGET_DIR"
if [ -d "$TARGET_DIR/.git" ]; then
  git -C "$TARGET_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$TARGET_DIR"
fi
cd "$TARGET_DIR"

echo "==> dependências"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r server/requirements.txt
PATH="$TARGET_DIR/.venv/bin:$PATH" bash generate_stubs.sh

echo "==> configuração"
cat > "$TARGET_DIR/server.env" <<ENV
GRPC_HOST=0.0.0.0
CARDS_ADDR=$CARDS_ADDR
PGHOST=$PGHOST
PGPORT=$PGPORT
PGDATABASE=$PGDATABASE
PGUSER=$PGUSER
PGPASSWORD=$PGPASSWORD
PGSSLMODE=$PGSSLMODE
ENV
chmod 600 "$TARGET_DIR/server.env"

echo "==> serviço"
cp infra/expenses.service /etc/systemd/system/expenses.service
systemctl daemon-reload
systemctl enable expenses
systemctl restart expenses
sleep 3
systemctl is-active expenses

echo
echo "Pronto. Gastos escuta em $(hostname -I | awk '{print $1}'):50051"
echo "Anote este IP interno: a vm-server precisa dele."
echo "Log:  journalctl -u expenses -f"
