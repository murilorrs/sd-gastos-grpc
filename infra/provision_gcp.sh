#!/usr/bin/env bash
# Provisiona o sistema inteiro do zero numa conta GCP: APIs, rede privada,
# Cloud SQL, firewall e as quatro VMs já configuradas.
#
#   bash infra/provision_gcp.sh
#
# Antes de rodar, só duas coisas precisam estar prontas na mão:
#   1. gcloud instalado e autenticado   (gcloud auth login)
#   2. uma conta de faturamento ativa   (console -> Faturamento)
#
# O script é idempotente: rodar de novo reaproveita o que já existe.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-${REGION}-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
REPO_URL="${REPO_URL:-https://github.com/murilorrs/sd-gastos-grpc.git}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

passo() { echo; echo "=====> $*"; }
ja()    { echo "       já existe: $*"; }


# ---------------------------------------------------------------- projeto
if [ -z "$PROJECT" ]; then
  PROJECT=$(gcloud config get-value project 2>/dev/null)
  [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ] && {
    echo "Defina o projeto:  PROJECT=meu-projeto bash infra/provision_gcp.sh"; exit 1; }
fi
gcloud config set project "$PROJECT" --quiet >/dev/null
echo "projeto: $PROJECT    região: $REGION    zona: $ZONE"

passo "faturamento"
if [ "$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null)" = "True" ]; then
  ja "faturamento ativo"
else
  if [ -z "$BILLING_ACCOUNT" ]; then
    BILLING_ACCOUNT=$(gcloud billing accounts list --filter="open=true" \
      --format="value(name)" --limit=1 2>/dev/null | sed 's#billingAccounts/##')
  fi
  [ -z "$BILLING_ACCOUNT" ] && {
    echo "Nenhuma conta de faturamento aberta. Crie uma no console e rode de novo."
    echo "Ou passe a sua:  BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX bash infra/provision_gcp.sh"
    exit 1; }
  gcloud billing projects link "$PROJECT" --billing-account="$BILLING_ACCOUNT"
fi

passo "APIs"
gcloud services enable compute.googleapis.com --quiet

# --------------------------------------------------------------- firewall
passo "firewall"
regra() {
  local nome=$1; shift
  if gcloud compute firewall-rules describe "$nome" --quiet >/dev/null 2>&1; then
    ja "$nome"
  else
    gcloud compute firewall-rules create "$nome" --network=default --quiet "$@"
  fi
}
regra allow-web-external --action=allow --direction=ingress \
  --rules=tcp:80 --source-ranges=0.0.0.0/0 --target-tags=grpc-client
regra allow-gateway-internal --action=allow --direction=ingress \
  --rules=tcp:8000 --source-ranges=10.128.0.0/9 --target-tags=grpc-server
regra allow-grpc-internal --action=allow --direction=ingress --priority=800 \
  --rules=tcp:50051,tcp:50052 --source-tags=grpc-server,grpc-service \
  --target-tags=grpc-service
regra deny-grpc-external --action=deny --direction=ingress --priority=900 \
  --rules=tcp:50051,tcp:50052 --source-ranges=0.0.0.0/0 --target-tags=grpc-service
regra allow-postgres-internal --action=allow --direction=ingress --priority=800 \
  --rules=tcp:5432 --source-tags=grpc-service --target-tags=db-server
regra deny-postgres-external --action=deny --direction=ingress --priority=900 \
  --rules=tcp:5432 --source-ranges=0.0.0.0/0 --target-tags=db-server

# Sem IP externo, as VMs só saem para a internet (apt, git clone, docker
# pull) pelo Cloud NAT.
passo "Cloud NAT"
if gcloud compute routers describe nat-router --region="$REGION" --quiet >/dev/null 2>&1; then
  ja "nat-router"
else
  gcloud compute routers create nat-router --network=default --region="$REGION" --quiet
  gcloud compute routers nats create nat-config --router=nat-router --region="$REGION" \
    --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges --quiet
  # ponytail: espera fixa; o NAT recém-criado leva ~1 min para dar saída, e
  # uma VM que liga antes disso falha no apt-get do script de inicialização.
  echo "       esperando o NAT ficar ativo (90s)"
  sleep 90
fi

# -------------------------------------------------------------------- VMs
DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)}"
JWT_SECRET="${JWT_SECRET:-$(openssl rand -base64 48 | tr -d '\n')}"
GATEWAY_USER="${GATEWAY_USER:-demo}"
GATEWAY_PASSWORD="${GATEWAY_PASSWORD:-$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)}"

# Preenche o bloco de CONFIGURAÇÃO do script de inicialização e devolve o
# caminho do arquivo pronto para ir como metadata da VM.
# "0,/^X=/" limita a troca à PRIMEIRA ocorrência — a do bloco de
# CONFIGURAÇÃO. Sem isso o sed também reescreveria as linhas do heredoc que
# monta o server.env, onde X=$X precisa continuar sendo a variável.
preparado() {
  local origem=$1 destino="$TMP/$(basename "$1")"; shift
  cp "$origem" "$destino"
  sed -i "0,/^REPO_URL=/s#^REPO_URL=.*#REPO_URL=\"$REPO_URL\"#" "$destino"
  while [ $# -gt 0 ]; do
    sed -i "0,/^$1=/s#^$1=.*#$1=\"$2\"#" "$destino"
    shift 2
  done
  echo "$destino"
}

cria_vm() {
  local nome=$1 tag=$2 script=$3 externo=$4
  if gcloud compute instances describe "$nome" --zone="$ZONE" --quiet >/dev/null 2>&1; then
    ja "VM $nome"
    return
  fi
  local args=(--zone="$ZONE" --machine-type="$MACHINE_TYPE"
              --image-family=debian-12 --image-project=debian-cloud
              --tags="$tag" --metadata-from-file=startup-script="$script")
  [ "$externo" = "nao" ] && args+=(--no-address)
  gcloud compute instances create "$nome" "${args[@]}" --quiet >/dev/null
  echo "       criada: $nome"
}

ip_interno() {
  gcloud compute instances describe "$1" --zone="$ZONE" \
    --format="value(networkInterfaces[0].networkIP)"
}

passo "vm-db"
cria_vm vm-db db-server "$(preparado infra/startup-db.sh \
  PGPASSWORD "$DB_PASSWORD")" nao
DB_IP=$(ip_interno vm-db)
echo "       postgres em $DB_IP:5432"

passo "vm-cards"
cria_vm vm-cards grpc-service "$(preparado infra/startup-cards.sh \
  PGHOST "$DB_IP" PGPASSWORD "$DB_PASSWORD")" nao
CARDS_IP=$(ip_interno vm-cards)

passo "vm-expenses"
cria_vm vm-expenses grpc-service "$(preparado infra/startup-expenses.sh \
  PGHOST "$DB_IP" PGPASSWORD "$DB_PASSWORD" CARDS_ADDR "$CARDS_IP:50052")" nao
EXPENSES_IP=$(ip_interno vm-expenses)

passo "vm-server"
cria_vm vm-server grpc-server "$(preparado infra/startup-server.sh \
  CARDS_ADDR "$CARDS_IP:50052" EXPENSES_ADDR "$EXPENSES_IP:50051" \
  JWT_SECRET "$JWT_SECRET" GATEWAY_USER "$GATEWAY_USER" \
  GATEWAY_PASSWORD "$GATEWAY_PASSWORD" ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY")" nao
SERVER_IP=$(ip_interno vm-server)

passo "vm-client"
cria_vm vm-client grpc-client "$(preparado infra/startup-client.sh \
  GATEWAY_HOST "$SERVER_IP")" sim
EXTERNO=$(gcloud compute instances describe vm-client --zone="$ZONE" \
  --format="value(networkInterfaces[0].accessConfigs[0].natIP)")

# ------------------------------------------------------------- resultado
cat > credenciais.txt <<FIM
projeto           $PROJECT
zona              $ZONE

interface web     http://$EXTERNO
usuário           $GATEWAY_USER
senha             $GATEWAY_PASSWORD

banco             $DB_IP:5432  (expenses / expenses_app, em container)
senha do banco    $DB_PASSWORD
jwt secret        $JWT_SECRET

vm-db             $DB_IP:5432
vm-cards          $CARDS_IP:50052
vm-expenses       $EXPENSES_IP:50051
vm-server         $SERVER_IP:8000
FIM
chmod 600 credenciais.txt

cat <<FIM

=====> pronto

  Interface web:  http://$EXTERNO
  Login:          $GATEWAY_USER / $GATEWAY_PASSWORD

  Tudo isso também ficou em credenciais.txt (fora do git).

As VMs ainda estão instalando — os scripts de inicialização levam de 3 a 8
minutos, e a vm-client é a mais lenta porque compila o frontend.

FIM

passo "esperando o sistema subir e semeando os dados de demonstração"
GATEWAY_USER="$GATEWAY_USER" GATEWAY_PASSWORD="$GATEWAY_PASSWORD" \
  ZONE="$ZONE" PROJECT="$PROJECT" bash infra/semeia.sh || {
    echo "       ainda não subiu. Rode depois:  bash infra/semeia.sh"; }

echo
bash infra/verifica.sh || true
echo
echo "=====> abra http://$EXTERNO e entre com $GATEWAY_USER / $GATEWAY_PASSWORD"
