#!/usr/bin/env bash
# Script de inicialização da vm-db.
#
# Sobe um PostgreSQL em container, na porta 5432. Quem alcança essa porta é
# controlado por firewall: só as VMs com a tag grpc-service. A VM não precisa
# de IP externo.
set -euo pipefail

# --------------------------- CONFIGURAÇÃO ---------------------------------
PGDATABASE="expenses"
PGUSER="expenses_app"
PGPASSWORD="TROQUE-PELA-SENHA-DO-BANCO"
PG_IMAGE="postgres:16-alpine"
# --------------------------------------------------------------------------

echo "==> docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io
systemctl enable --now docker

echo "==> postgres"
# O volume sobrevive ao container: reiniciar a VM não apaga os dados.
docker volume create pgdata >/dev/null
docker rm -f postgres >/dev/null 2>&1 || true
docker run -d --name postgres \
  --restart=always \
  -e POSTGRES_DB="$PGDATABASE" \
  -e POSTGRES_USER="$PGUSER" \
  -e POSTGRES_PASSWORD="$PGPASSWORD" \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  "$PG_IMAGE"

echo "==> esperando aceitar conexão"
for _ in $(seq 1 60); do
  if docker exec postgres pg_isready -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; then
    echo "pronto. PostgreSQL em $(hostname -I | awk '{print $1}'):5432"
    echo "Anote este IP interno: a vm-cards e a vm-expenses precisam dele."
    exit 0
  fi
  sleep 2
done

echo "!! o postgres não respondeu a tempo"
docker logs --tail 40 postgres
exit 1
