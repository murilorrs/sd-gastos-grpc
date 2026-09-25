#!/usr/bin/env bash
# Instala e sobe o sistema nas duas VMs.
#
# As duas clonam o MESMO repositório; o que muda é o que cada uma roda:
#   vm-server: Gateway FastAPI (:8000) + microsserviços de Cartões e de Gastos
#              (gRPC, só em 127.0.0.1), todos como serviços do systemd
#   vm-client: o cliente de terminal, que você roda à mão na apresentação
#
#   bash infra/deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
ROOT="$(cd .. && pwd)"
# Os temporários abaixo contêm segredos: apaga mesmo se o script falhar no meio.
trap 'rm -f "$ROOT/.server.env.tmp" "$ROOT/.client.env.tmp"' EXIT

GATEWAY_PORT=8000
INTERNAL_IP=$(gcloud compute instances describe "$VM_SERVER" --zone="$ZONE" \
  --format="get(networkInterfaces[0].networkIP)")

# ---------------------------------------------------------------------------
echo "==> $VM_SERVER (gateway + cards + expenses)"
# ---------------------------------------------------------------------------
# O .env local guarda os segredos dos dois lados. Cada VM recebe só a sua
# parte. A vm-server recebe o banco (PG*) e o que o Gateway usa para emitir e
# conferir tokens (JWT_SECRET, GATEWAY_USER, GATEWAY_PASSWORD).
SERVER_VARS='^(PG[A-Z]*|JWT_SECRET|GATEWAY_USER|GATEWAY_PASSWORD)='
if [ -f "$ROOT/.env" ] && grep -qE "$SERVER_VARS" "$ROOT/.env"; then
  echo "==> copying server secrets to $VM_SERVER"
  grep -E "$SERVER_VARS" "$ROOT/.env" > "$ROOT/.server.env.tmp"
  gcloud compute scp "$ROOT/.server.env.tmp" "$VM_SERVER:/tmp/server.env" --zone="$ZONE"
  rm -f "$ROOT/.server.env.tmp"
else
  echo "!! no server variables in $ROOT/.env; SQLite and a random JWT secret will be used"
fi

SERVER_SCRIPT=$(cat <<EOF
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv git
sudo mkdir -p $TARGET_DIR
sudo chown -R \$(whoami) $TARGET_DIR
if [ -d $TARGET_DIR/.git ]; then
  git -C $TARGET_DIR pull --ff-only
else
  git clone $REPO_URL $TARGET_DIR
fi
cd $TARGET_DIR
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r server/requirements.txt -r gateway/requirements.txt
PATH=$TARGET_DIR/.venv/bin:\$PATH bash generate_stubs.sh
if [ -f /tmp/server.env ]; then
  # Só root lê: o arquivo tem a senha do banco e o segredo do JWT.
  sudo install -m 600 -o root /tmp/server.env $TARGET_DIR/server.env
  rm -f /tmp/server.env
fi
for unit in cards expenses gateway; do
  sudo cp infra/\$unit.service /etc/systemd/system/\$unit.service
done
sudo systemctl daemon-reload
sudo systemctl enable cards expenses gateway
sudo systemctl restart cards expenses gateway
sleep 2
systemctl is-active cards expenses gateway
EOF
)
gcloud compute ssh "$VM_SERVER" --zone="$ZONE" --command "$SERVER_SCRIPT"

# ---------------------------------------------------------------------------
echo
echo "==> $VM_CLIENT (terminal client)"
# ---------------------------------------------------------------------------
CLIENT_SCRIPT=$(cat <<EOF
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv git
sudo mkdir -p $TARGET_DIR
sudo chown -R \$(whoami) $TARGET_DIR
if [ -d $TARGET_DIR/.git ]; then
  git -C $TARGET_DIR pull --ff-only
else
  git clone $REPO_URL $TARGET_DIR
fi
cd $TARGET_DIR
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r client/requirements.txt
EOF
)
gcloud compute ssh "$VM_CLIENT" --zone="$ZONE" --command "$CLIENT_SCRIPT"

# A vm-client recebe a chave da LLM, o login do Gateway e o endereço dele —
# nunca a senha do banco nem o segredo do JWT: ela só fala com o Gateway.
if [ -f "$ROOT/.env" ]; then
  echo "==> copying client settings to $VM_CLIENT"
  grep -vE '^(PG[A-Z]*|JWT_SECRET|GATEWAY_URL)=' "$ROOT/.env" > "$ROOT/.client.env.tmp"
  echo "GATEWAY_URL=http://$INTERNAL_IP:$GATEWAY_PORT" >> "$ROOT/.client.env.tmp"
  gcloud compute scp "$ROOT/.client.env.tmp" "$VM_CLIENT:$TARGET_DIR/.env" --zone="$ZONE"
  rm -f "$ROOT/.client.env.tmp"
else
  echo "!! $ROOT/.env not found; the client on the VM will ask for the login"
fi

cat <<END

Deploy finished.

  Gateway: http://$INTERNAL_IP:$GATEWAY_PORT  (docs em /docs)

To use the system:

  gcloud compute ssh $VM_CLIENT --zone=$ZONE
  cd $TARGET_DIR && .venv/bin/python client/client.py --verbose

To watch the server logs (gateway and both microservices together):

  gcloud compute ssh $VM_SERVER --zone=$ZONE --command "sudo journalctl -u gateway -u cards -u expenses -f"
END
