#!/usr/bin/env bash
# Cria a infraestrutura do trabalho no GCP: duas VMs e a regra de firewall
# que libera o gRPC apenas dentro da VPC.
#
# Idempotente: rodar de novo não duplica nada.
#
#   cp infra/config.sh.example infra/config.sh   # e edite o PROJECT
#   bash infra/setup_gcp.sh
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

gcloud config set project "$PROJECT" --quiet
gcloud services enable compute.googleapis.com --quiet

# ---------------------------------------------------------------------------
# Regra de firewall do API Gateway.
#
# Desde o Trabalho 2, a única porta da vm-server que atende quem vem de fora
# dela é a 8000 do Gateway; os microsserviços gRPC escutam só em 127.0.0.1.
# As duas restrições são o que faz esta regra significar alguma coisa:
#   --source-ranges  só aceita tráfego da faixa interna da VPC (nada da internet)
#   --target-tags    só se aplica às VMs marcadas como grpc-server
#
# (A regra allow-grpc-internal, da porta 50051, era do Trabalho 1, quando o
# cliente falava gRPC direto com o servidor. Não é mais usada.)
# ---------------------------------------------------------------------------
GATEWAY_PORT=8000
if gcloud compute firewall-rules describe allow-gateway-internal --quiet >/dev/null 2>&1; then
  echo "==> firewall rule allow-gateway-internal already exists"
else
  echo "==> creating firewall rule allow-gateway-internal"
  gcloud compute firewall-rules create allow-gateway-internal \
    --network=default \
    --action=allow \
    --direction=ingress \
    --rules="tcp:${GATEWAY_PORT}" \
    --source-ranges=10.128.0.0/9 \
    --target-tags=grpc-server \
    --description="API gateway only inside the VPC, only for VMs tagged grpc-server"
fi

create_vm() {
  local name=$1 tag=$2
  if gcloud compute instances describe "$name" --zone="$ZONE" --quiet >/dev/null 2>&1; then
    echo "==> VM $name already exists — reusing it"
    # add-tags é aditivo: preserva tags que a VM já tinha (ex.: http-server
    # criada pelo console), em vez de sobrescrever a lista inteira.
    gcloud compute instances add-tags "$name" --zone="$ZONE" --tags="$tag" --quiet
    local status
    status=$(gcloud compute instances describe "$name" --zone="$ZONE" --format="value(status)")
    if [ "$status" != "RUNNING" ]; then
      echo "==> starting $name (was $status)"
      gcloud compute instances start "$name" --zone="$ZONE" --quiet
    fi
    return
  fi
  echo "==> creating VM $name"
  gcloud compute instances create "$name" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --tags="$tag"
}

# A vm-client recebe um IP externo efêmero por padrão, e precisa dele para
# alcançar a API da LLM. A vm-server não depende de saída para a internet.
create_vm "$VM_SERVER" grpc-server
create_vm "$VM_CLIENT" grpc-client

echo
echo "==> instances"
gcloud compute instances list --zones="$ZONE"
echo
echo "==> firewall rule"
gcloud compute firewall-rules describe allow-gateway-internal \
  --format="table(name, sourceRanges.list(), targetTags.list(), allowed[].map().firewall_rule().list())"
echo
echo "Next step:  bash infra/deploy.sh"
