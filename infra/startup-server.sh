#!/usr/bin/env bash
# Script de inicialização da vm-server — cole no campo "Script de inicialização"
# ao criar a VM no Google Cloud Console (Gerenciamento -> Automação), ou rode à
# mão pelo SSH do navegador.
#
# Sobe o API Gateway na porta 8000, como serviço do systemd. Os dois
# microsserviços gRPC vivem nas suas próprias VMs (vm-cards e vm-expenses) e
# precisam estar no ar antes desta: os endereços deles vão na configuração
# abaixo.
#
# Antes de usar, preencha o bloco de CONFIGURAÇÃO abaixo. Ele é a única parte
# que muda de um grupo para outro.
set -euo pipefail

# --------------------------- CONFIGURAÇÃO ---------------------------------
REPO_URL="https://github.com/murilorrs/sd-gastos-grpc.git"
TARGET_DIR="/opt/sd-gastos-grpc"

CARDS_ADDR="10.128.0.4:50052"
EXPENSES_ADDR="10.128.0.5:50051"

# Gateway: segredo de assinatura do JWT e o login aceito em POST /auth/token.
# Gere o segredo com:  openssl rand -base64 48
JWT_SECRET="TROQUE-POR-UM-SEGREDO-LONGO-E-ALEATORIO"
GATEWAY_USER="demo"
GATEWAY_PASSWORD="TROQUE-ESTA-SENHA"

# Opcional: a chave da Anthropic habilita a interpretação em linguagem natural.
# Sem ela o sistema funciona igual, usando o interpretador por regras.
ANTHROPIC_API_KEY=""
ANTHROPIC_MODEL="claude-haiku-4-5"

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
CARDS_ADDR=$CARDS_ADDR
EXPENSES_ADDR=$EXPENSES_ADDR
JWT_SECRET=$JWT_SECRET
GATEWAY_USER=$GATEWAY_USER
GATEWAY_PASSWORD=$GATEWAY_PASSWORD
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
ANTHROPIC_MODEL=$ANTHROPIC_MODEL
ENV
chmod 600 "$TARGET_DIR/server.env"
chown root:root "$TARGET_DIR/server.env"

echo "==> serviço"
cp infra/gateway.service /etc/systemd/system/gateway.service
systemctl daemon-reload
systemctl enable gateway
systemctl restart gateway
sleep 3
systemctl is-active gateway

echo
echo "Pronto. O Gateway responde em http://$(hostname -I | awk '{print $1}'):8000"
echo "Anote este IP interno: a vm-client precisa dele."
echo "Log:  journalctl -u gateway -f"
echo
echo "Conferindo o alcance dos microsserviços:"
curl -s -o /dev/null -w "  gateway  /health -> %{http_code}\n" "http://localhost:8000/health"
