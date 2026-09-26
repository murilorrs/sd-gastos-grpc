#!/usr/bin/env bash
# Script de inicialização da vm-server — cole no campo "Script de inicialização"
# ao criar a VM no Google Cloud Console (Gerenciamento -> Automação), ou rode à
# mão pelo SSH do navegador.
#
# Sobe o Gateway (porta 8000) e os dois microsserviços gRPC (só em 127.0.0.1)
# como serviços do systemd, que voltam sozinhos se a VM reiniciar.
#
# Antes de usar, preencha o bloco de CONFIGURAÇÃO abaixo. Ele é a única parte
# que muda de um grupo para outro.
set -euo pipefail

# --------------------------- CONFIGURAÇÃO ---------------------------------
REPO_URL="https://github.com/murilorrs/sd-gastos-grpc.git"
TARGET_DIR="/opt/sd-gastos-grpc"

# Cloud SQL (PostgreSQL). Use o IP PRIVADO da instância, que aparece no console
# em SQL -> sua instância -> Visão geral -> Conectar-se a esta instância.
PGHOST="10.115.48.3"
PGPORT="5432"
PGDATABASE="expenses"
PGUSER="expenses_app"
PGPASSWORD="TROQUE-PELA-SENHA-DO-BANCO"

# Gateway: segredo de assinatura do JWT e o login aceito em POST /auth/token.
# Gere o segredo com:  openssl rand -base64 48
JWT_SECRET="TROQUE-POR-UM-SEGREDO-LONGO-E-ALEATORIO"
GATEWAY_USER="demo"
GATEWAY_PASSWORD="TROQUE-ESTA-SENHA"

# Opcional: a chave da Anthropic habilita a interpretação em linguagem natural.
# Sem ela o sistema funciona igual, usando o interpretador por regras.
ANTHROPIC_API_KEY=""
ANTHROPIC_MODEL="claude-haiku-4-5"
# --------------------------------------------------------------------------

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
.venv/bin/pip install -q -r server/requirements.txt -r gateway/requirements.txt
PATH="$TARGET_DIR/.venv/bin:$PATH" bash generate_stubs.sh

echo "==> segredos"
# Só root lê: o arquivo tem a senha do banco e o segredo do JWT.
cat > "$TARGET_DIR/server.env" <<ENV
PGHOST=$PGHOST
PGPORT=$PGPORT
PGDATABASE=$PGDATABASE
PGUSER=$PGUSER
PGPASSWORD=$PGPASSWORD
JWT_SECRET=$JWT_SECRET
GATEWAY_USER=$GATEWAY_USER
GATEWAY_PASSWORD=$GATEWAY_PASSWORD
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
ANTHROPIC_MODEL=$ANTHROPIC_MODEL
ENV
chmod 600 "$TARGET_DIR/server.env"
chown root:root "$TARGET_DIR/server.env"

echo "==> serviços"
for unit in cards expenses gateway; do
  cp "infra/$unit.service" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
systemctl enable cards expenses gateway
systemctl restart cards expenses gateway
sleep 3
systemctl is-active cards expenses gateway

echo
echo "Pronto. O Gateway responde em http://$(hostname -I | awk '{print $1}'):8000"
echo "Logs dos três juntos:  journalctl -u gateway -u cards -u expenses -f"
