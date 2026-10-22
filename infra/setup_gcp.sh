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

if gcloud compute firewall-rules describe allow-web-external --quiet >/dev/null 2>&1; then
  echo "==> firewall rule allow-web-external already exists"
else
  echo "==> creating firewall rule allow-web-external"
  gcloud compute firewall-rules create allow-web-external \
    --network=default \
    --action=allow \
    --direction=ingress \
    --rules=tcp:80 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=grpc-client \
    --description="Web frontend (nginx) on the client VM - the only port open to the internet"
fi

if gcloud compute firewall-rules describe allow-grpc-internal --quiet >/dev/null 2>&1; then
  echo "==> firewall rule allow-grpc-internal already exists"
else
  echo "==> creating firewall rule allow-grpc-internal"
  gcloud compute firewall-rules create allow-grpc-internal \
    --network=default \
    --action=allow \
    --direction=ingress \
    --priority=800 \
    --rules=tcp:50051,tcp:50052 \
    --source-tags=grpc-server,grpc-service \
    --target-tags=grpc-service \
    --description="gRPC microservices: only the gateway and each other"
fi

if gcloud compute firewall-rules describe deny-grpc-external --quiet >/dev/null 2>&1; then
  echo "==> firewall rule deny-grpc-external already exists"
else
  echo "==> creating firewall rule deny-grpc-external"
  gcloud compute firewall-rules create deny-grpc-external \
    --network=default \
    --action=deny \
    --direction=ingress \
    --priority=900 \
    --rules=tcp:50051,tcp:50052 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=grpc-service \
    --description="Everyone else is refused, including other VMs in the VPC"
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
create_vm "$VM_CARDS" grpc-service
create_vm "$VM_EXPENSES" grpc-service
create_vm "$VM_SERVER" grpc-server
create_vm "$VM_CLIENT" grpc-client

echo
echo "==> instances"
gcloud compute instances list --zones="$ZONE"
echo
echo "==> firewall rules"
gcloud compute firewall-rules list \
  --filter="name=(allow-gateway-internal,allow-web-external,allow-grpc-internal,deny-grpc-external)" \
  --format="table(name, priority, sourceRanges.list(), sourceTags.list(), targetTags.list(), allowed[].map().firewall_rule().list(), denied[].map().firewall_rule().list())"
echo
echo "Next step:  bash infra/deploy.sh"
