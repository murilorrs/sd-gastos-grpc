#!/usr/bin/env bash
# Instala e sobe os serviços nas duas VMs.
#
# As duas clonam o MESMO repositório; o que muda é qual processo cada uma roda.
# A vm-server sobe o server.py como serviço do systemd; a vm-client só fica
# preparada, porque o cliente é um REPL que você roda à mão na apresentação.
#
#   bash infra/deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
ROOT="$(cd .. && pwd)"
# Os temporários abaixo contêm segredos: apaga mesmo se o script falhar no meio.
trap 'rm -f "$ROOT/.server.env.tmp" "$ROOT/.client.env.tmp"' EXIT

# ---------------------------------------------------------------------------
echo "==> $VM_SERVER (Microservice B)"
# ---------------------------------------------------------------------------
# O .env local guarda os segredos dos dois lados. Cada VM recebe só a sua
# parte: as variáveis PG* (banco) vão para a vm-server, o resto (chave da LLM)
# para a vm-client. A vm-client alcança o banco pela VPC, então dar a senha a
# ela seria acesso sem necessidade.
if [ -f "$ROOT/.env" ] && grep -q '^PG' "$ROOT/.env"; then
  echo "==> copying database credentials to $VM_SERVER"
  grep '^PG' "$ROOT/.env" > "$ROOT/.server.env.tmp"
  gcloud compute scp "$ROOT/.server.env.tmp" "$VM_SERVER:/tmp/server.env" --zone="$ZONE"
  rm -f "$ROOT/.server.env.tmp"
else
  echo "!! no PG* variables in $ROOT/.env; the server will use SQLite"
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
.venv/bin/pip install -q -r server/requirements.txt
.venv/bin/python -m grpc_tools.protoc -I proto \
  --python_out=server --grpc_python_out=server proto/expenses.proto
if [ -f /tmp/server.env ]; then
  # Só root lê: o arquivo tem a senha do banco.
  sudo install -m 600 -o root /tmp/server.env $TARGET_DIR/server.env
  rm -f /tmp/server.env
fi
sudo cp infra/expenses.service /etc/systemd/system/expenses.service
sudo systemctl daemon-reload
sudo systemctl enable expenses
sudo systemctl restart expenses
sleep 1
systemctl is-active expenses
EOF
)
gcloud compute ssh "$VM_SERVER" --zone="$ZONE" --command "$SERVER_SCRIPT"

# ---------------------------------------------------------------------------
echo
echo "==> $VM_CLIENT (Microservice A)"
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
.venv/bin/python -m grpc_tools.protoc -I proto \
  --python_out=client --grpc_python_out=client proto/expenses.proto
EOF
)
gcloud compute ssh "$VM_CLIENT" --zone="$ZONE" --command "$CLIENT_SCRIPT"

# A chave da API vai só para a vm-client. A vm-server não a tem — mesmo que
# alguém rodasse o cliente lá por engano, ele não funcionaria. As variáveis PG*
# ficam de fora pelo mesmo motivo, no sentido inverso.
if [ -f "$ROOT/.env" ]; then
  echo "==> copying .env (without PG* variables) to $VM_CLIENT"
  grep -v '^PG' "$ROOT/.env" > "$ROOT/.client.env.tmp"
  gcloud compute scp "$ROOT/.client.env.tmp" "$VM_CLIENT:$TARGET_DIR/.env" --zone="$ZONE"
  rm -f "$ROOT/.client.env.tmp"
else
  echo "!! $ROOT/.env not found; the client on the VM will only work with --offline"
fi

INTERNAL_IP=$(gcloud compute instances describe "$VM_SERVER" --zone="$ZONE" \
  --format="get(networkInterfaces[0].networkIP)")

cat <<END

Deploy finished.

  Server internal IP: $INTERNAL_IP

To use the system:

  gcloud compute ssh $VM_CLIENT --zone=$ZONE
  cd $TARGET_DIR && .venv/bin/python client/client.py --server $INTERNAL_IP:$PORT

To watch the server logs:

  gcloud compute ssh $VM_SERVER --zone=$ZONE --command "sudo journalctl -u expenses -f"
END
