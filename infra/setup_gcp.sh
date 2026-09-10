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
# Regra de firewall — requisito 3 do trabalho.
#
# As duas restrições são o que faz esta regra significar alguma coisa:
#   --source-ranges  só aceita tráfego da faixa interna da VPC (nada da internet)
#   --target-tags    só se aplica às VMs marcadas como grpc-server
# Sem elas seria "abri a porta 50051 para o mundo", que é o oposto do pedido.
# ---------------------------------------------------------------------------
if gcloud compute firewall-rules describe allow-grpc-internal --quiet >/dev/null 2>&1; then
  echo "==> firewall rule allow-grpc-internal already exists"
else
  echo "==> creating firewall rule allow-grpc-internal"
  gcloud compute firewall-rules create allow-grpc-internal \
    --network=default \
    --action=allow \
    --direction=ingress \
    --rules="tcp:${PORT}" \
    --source-ranges=10.128.0.0/9 \
    --target-tags=grpc-server \
    --description="gRPC only inside the VPC, only for VMs tagged grpc-server"
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
gcloud compute firewall-rules describe allow-grpc-internal \
  --format="table(name, sourceRanges.list(), targetTags.list(), allowed[].map().firewall_rule().list())"
echo
echo "Next step:  bash infra/deploy.sh"
