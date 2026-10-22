#!/usr/bin/env bash
# Script de inicialização da vm-cards — cole no campo "Script de inicialização"
# ao criar a VM no Google Cloud Console (Gerenciamento -> Automação).
#
# Sobe apenas o microsserviço de Cartões, na porta 50052, como serviço do
# systemd. Ele não depende de nenhum outro serviço: suba esta VM primeiro.
#
# Quem alcança esta porta é controlado por firewall — veja a regra
# allow-grpc-internal em docs/GCP-CONSOLE.md. A VM não precisa de IP externo.
set -euo pipefail

# --------------------------- CONFIGURAÇÃO ---------------------------------
REPO_URL="https://github.com/murilorrs/sd-gastos-grpc.git"
TARGET_DIR="/opt/sd-gastos-grpc"

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
# GRPC_HOST=0.0.0.0 porque o serviço tem esta VM só para ele: quem o chama
# vem de outra máquina. O isolamento aqui é do firewall, não do loopback.
cat > "$TARGET_DIR/server.env" <<ENV
GRPC_HOST=0.0.0.0
PGHOST=$PGHOST
PGPORT=$PGPORT
PGDATABASE=$PGDATABASE
PGUSER=$PGUSER
PGPASSWORD=$PGPASSWORD
PGSSLMODE=$PGSSLMODE
ENV
chmod 600 "$TARGET_DIR/server.env"

echo "==> serviço"
cp infra/cards.service /etc/systemd/system/cards.service
systemctl daemon-reload
systemctl enable cards
systemctl restart cards
sleep 3
systemctl is-active cards

echo
echo "Pronto. Cartões escuta em $(hostname -I | awk '{print $1}'):50052"
echo "Anote este IP interno: a vm-expenses e a vm-server precisam dele."
echo "Log:  journalctl -u cards -f"
