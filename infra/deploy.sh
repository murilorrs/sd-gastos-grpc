#!/usr/bin/env bash
# Instala e sobe o sistema nas quatro VMs.
#
# Todas clonam o MESMO repositório; o que muda é o que cada uma roda:
#   vm-cards    microsserviço de Cartões (gRPC :50052)
#   vm-expenses microsserviço de Gastos  (gRPC :50051), que chama Cartões
#   vm-server   API Gateway (HTTP :8000), que chama os dois
#   vm-client   nginx (:80) servindo o frontend e repassando /api
#
# A ordem importa: cada uma precisa do IP interno da anterior.
#
#   bash infra/deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
ROOT="$(cd .. && pwd)"
trap 'rm -f "$ROOT"/.*.env.tmp' EXIT

GATEWAY_PORT=8000

internal_ip() {
  gcloud compute instances describe "$1" --zone="$ZONE" \
    --format="get(networkInterfaces[0].networkIP)"
}

# Tudo que é comum às quatro: pacotes, clone e ambiente virtual.
base_script() {
  cat <<EOF
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
EOF
}

# Envia o server.env com os segredos daquela VM e instala a unit do systemd.
# O arquivo vai por scp e só root o lê: tem a senha do banco.
install_service() {
  local vm=$1 unit=$2 envfile=$3
  gcloud compute scp "$envfile" "$vm:/tmp/server.env" --zone="$ZONE" --quiet
  gcloud compute ssh "$vm" --zone="$ZONE" --quiet --command "
    set -euo pipefail
    cd $TARGET_DIR
    sudo install -m 600 -o root /tmp/server.env $TARGET_DIR/server.env
    rm -f /tmp/server.env
    sudo cp infra/$unit.service /etc/systemd/system/$unit.service
    sudo systemctl daemon-reload
    sudo systemctl enable $unit
    sudo systemctl restart $unit
    sleep 3
    systemctl is-active $unit"
}

# As credenciais do banco saem do .env local e vão só para quem toca o banco:
# os dois microsserviços. O Gateway não as recebe — ele não fala com o banco.
db_env() { grep -E '^PG[A-Z]*=' "$ROOT/.env" 2>/dev/null || true; }

echo "==> $VM_CARDS (microsserviço de Cartões)"

gcloud compute ssh "$VM_CARDS" --zone="$ZONE" --quiet --command "$(base_script)
.venv/bin/pip install -q -r server/requirements.txt
PATH=$TARGET_DIR/.venv/bin:\$PATH bash generate_stubs.sh"

{ echo "GRPC_HOST=0.0.0.0"; db_env; } > "$ROOT/.cards.env.tmp"
install_service "$VM_CARDS" cards "$ROOT/.cards.env.tmp"
CARDS_IP=$(internal_ip "$VM_CARDS")
echo "    Cartões em $CARDS_IP:50052"

echo
echo "==> $VM_EXPENSES (microsserviço de Gastos)"

gcloud compute ssh "$VM_EXPENSES" --zone="$ZONE" --quiet --command "$(base_script)
.venv/bin/pip install -q -r server/requirements.txt
PATH=$TARGET_DIR/.venv/bin:\$PATH bash generate_stubs.sh"

{ echo "GRPC_HOST=0.0.0.0"; echo "CARDS_ADDR=$CARDS_IP:50052"; db_env; } \
  > "$ROOT/.expenses.env.tmp"
install_service "$VM_EXPENSES" expenses "$ROOT/.expenses.env.tmp"
EXPENSES_IP=$(internal_ip "$VM_EXPENSES")
echo "    Gastos em $EXPENSES_IP:50051"

echo
echo "==> $VM_SERVER (API Gateway)"

gcloud compute ssh "$VM_SERVER" --zone="$ZONE" --quiet --command "$(base_script)
.venv/bin/pip install -q -r server/requirements.txt -r gateway/requirements.txt
PATH=$TARGET_DIR/.venv/bin:\$PATH bash generate_stubs.sh"

{
  echo "CARDS_ADDR=$CARDS_IP:50052"
  echo "EXPENSES_ADDR=$EXPENSES_IP:50051"
  grep -E '^(JWT_SECRET|GATEWAY_USER|GATEWAY_PASSWORD|ANTHROPIC_[A-Z_]*)=' \
    "$ROOT/.env" 2>/dev/null || true
} > "$ROOT/.gateway.env.tmp"
install_service "$VM_SERVER" gateway "$ROOT/.gateway.env.tmp"
SERVER_IP=$(internal_ip "$VM_SERVER")
echo "    Gateway em $SERVER_IP:$GATEWAY_PORT"

echo
echo "==> $VM_CLIENT (frontend web)"

gcloud compute ssh "$VM_CLIENT" --zone="$ZONE" --quiet --command "$(base_script)
.venv/bin/pip install -q -r client/requirements.txt
sudo apt-get install -y -qq nginx curl ca-certificates

# O Node do Debian 12 é antigo demais para o Vite 7; o NodeSource traz o 20 LTS.
if ! command -v node >/dev/null || [ \"\$(node -v | cut -c2-3)\" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y -qq nodejs
fi

cd $TARGET_DIR/web
npm ci --silent || npm install --silent
npm run build

sudo sed \"s#GATEWAY_HOST#$SERVER_IP#g\" $TARGET_DIR/infra/nginx.conf \
  | sudo tee /etc/nginx/sites-available/gastos >/dev/null
sudo ln -sf /etc/nginx/sites-available/gastos /etc/nginx/sites-enabled/gastos
sudo rm -f /etc/nginx/sites-enabled/default
chmod -R o+rX $TARGET_DIR/web/dist
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx"

# Só a vm-client recebe o endereço do Gateway e o login; nunca a senha do banco.
if [ -f "$ROOT/.env" ]; then
  grep -vE '^(PG[A-Z]*|JWT_SECRET|GATEWAY_URL|CARDS_ADDR|EXPENSES_ADDR)=' "$ROOT/.env" \
    > "$ROOT/.client.env.tmp"
  echo "GATEWAY_URL=http://$SERVER_IP:$GATEWAY_PORT" >> "$ROOT/.client.env.tmp"
  gcloud compute scp "$ROOT/.client.env.tmp" "$VM_CLIENT:$TARGET_DIR/.env" \
    --zone="$ZONE" --quiet
fi

EXTERNAL_IP=$(gcloud compute instances describe "$VM_CLIENT" --zone="$ZONE" \
  --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

cat <<END

Deploy finished.

  Interface web: http://$EXTERNAL_IP          <- abra isto no navegador
  Gateway:       http://$SERVER_IP:$GATEWAY_PORT   (interno; docs em /docs)
  Cartões:       $CARDS_IP:50052               (interno, só do Gateway e do Gastos)
  Gastos:        $EXPENSES_IP:50051            (interno, só do Gateway)

Sem IP externo na vm-client, chegue por um túnel SSH:

  gcloud compute ssh $VM_CLIENT --zone=$ZONE -- -L 8080:localhost:80
  # e abra http://localhost:8080

Logs, uma janela por serviço:

  gcloud compute ssh $VM_SERVER   --zone=$ZONE --command "sudo journalctl -u gateway -f"
  gcloud compute ssh $VM_EXPENSES --zone=$ZONE --command "sudo journalctl -u expenses -f"
  gcloud compute ssh $VM_CARDS    --zone=$ZONE --command "sudo journalctl -u cards -f"

O mesmo [id] aparece nos três: é a mesma requisição atravessando o sistema.
END
