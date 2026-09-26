#!/usr/bin/env bash
# Script de inicialização da vm-client — cole no campo "Script de inicialização"
# ao criar a VM no Google Cloud Console (Gerenciamento -> Automação), ou rode à
# mão pelo SSH do navegador.
#
# Instala o nginx, compila o frontend React e o publica na porta 80,
# repassando /api para o Gateway da vm-server. É a máquina que o navegador da
# apresentação acessa; a vm-server continua sem porta aberta para a internet.
set -euo pipefail

# --------------------------- CONFIGURAÇÃO ---------------------------------
REPO_URL="https://github.com/murilorrs/sd-gastos-grpc.git"
TARGET_DIR="/opt/sd-gastos-grpc"

# IP INTERNO da vm-server (a coluna "IP interno" em Compute Engine -> Instâncias
# de VM). Interno, não externo: as duas VMs conversam dentro da VPC.
GATEWAY_HOST="10.128.0.2"
# --------------------------------------------------------------------------

echo "==> pacotes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git nginx curl ca-certificates

# O Node do Debian 12 é antigo demais para o Vite 7; o repositório do NodeSource
# traz o 20 LTS, que é o mínimo que ele exige.
if ! command -v node >/dev/null || [ "$(node -v | cut -c2-3)" -lt 20 ]; then
  echo "==> node 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> código"
mkdir -p "$TARGET_DIR"
if [ -d "$TARGET_DIR/.git" ]; then
  git -C "$TARGET_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$TARGET_DIR"
fi

echo "==> build do frontend"
cd "$TARGET_DIR/web"
npm ci --silent || npm install --silent
npm run build

echo "==> nginx"
sed "s#GATEWAY_HOST#$GATEWAY_HOST#g" "$TARGET_DIR/infra/nginx.conf" \
  > /etc/nginx/sites-available/gastos
ln -sf /etc/nginx/sites-available/gastos /etc/nginx/sites-enabled/gastos
rm -f /etc/nginx/sites-enabled/default
# O nginx precisa atravessar /opt/sd-gastos-grpc/web/dist para ler os arquivos.
chmod -R o+rX "$TARGET_DIR/web/dist"
nginx -t
systemctl enable nginx
systemctl restart nginx

echo
echo "Pronto. Abra no navegador:  http://$(curl -s -H 'Metadata-Flavor: Google' \
  metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip \
  || echo '<IP-EXTERNO-DA-VM-CLIENT>')"
