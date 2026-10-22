#!/usr/bin/env bash
# Confere se o sistema está no ar e se o isolamento está valendo.
#
#   bash infra/verifica.sh
#
# Roda da sua máquina, por SSH nas VMs. Pode rodar quantas vezes quiser —
# não altera nada.
set -uo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
gcloud config set project "$PROJECT" --quiet >/dev/null 2>&1

ok=0; falhou=0
sim() { echo "  [ ok ] $*"; ok=$((ok+1)); }
nao() { echo "  [FALHA] $*"; falhou=$((falhou+1)); }

remoto() { gcloud compute ssh "$1" --zone="$ZONE" --quiet --command "$2" 2>/dev/null; }

echo "projeto $PROJECT, zona $ZONE"
echo
echo "== VMs =="
for vm in vm-db vm-cards vm-expenses vm-server vm-client; do
  estado=$(gcloud compute instances describe "$vm" --zone="$ZONE" \
    --format="value(status)" 2>/dev/null)
  [ "$estado" = "RUNNING" ] && sim "$vm está RUNNING" || nao "$vm está ${estado:-ausente}"
done

echo
echo "== serviços =="
remoto vm-db "sudo docker exec postgres pg_isready -U expenses_app -d expenses" \
  | grep -q "accepting connections" && sim "postgres aceitando conexão" || nao "postgres fora (docker logs postgres)"
remoto vm-cards    "systemctl is-active cards"    | grep -qx active && sim "cards no ar"    || nao "cards fora (journalctl -u cards)"
remoto vm-expenses "systemctl is-active expenses" | grep -qx active && sim "expenses no ar" || nao "expenses fora (journalctl -u expenses)"
remoto vm-server   "systemctl is-active gateway"  | grep -qx active && sim "gateway no ar"  || nao "gateway fora (journalctl -u gateway)"
remoto vm-client   "systemctl is-active nginx"    | grep -qx active && sim "nginx no ar"    || nao "nginx fora"

echo
echo "== conectividade =="
remoto vm-server "curl -s -m 5 localhost:8000/health" | grep -q '"ok"' \
  && sim "gateway responde /health" || nao "gateway não responde"
remoto vm-expenses "timeout 5 bash -c '</dev/tcp/$(gcloud compute instances describe vm-cards --zone=$ZONE --format="value(networkInterfaces[0].networkIP)" 2>/dev/null)/50052' 2>/dev/null && echo alcanca" \
  | grep -q alcanca && sim "expenses alcança cards" || nao "expenses NÃO alcança cards"

DB_IP=$(gcloud compute instances describe vm-db --zone="$ZONE" \
  --format="value(networkInterfaces[0].networkIP)" 2>/dev/null)
remoto vm-expenses "timeout 5 bash -c '</dev/tcp/$DB_IP/5432' 2>/dev/null && echo alcanca" \
  | grep -q alcanca && sim "expenses alcança o banco" || nao "expenses NÃO alcança o banco"

echo
echo "== isolamento (o que NÃO pode funcionar) =="
CARDS_IP=$(gcloud compute instances describe vm-cards --zone="$ZONE" \
  --format="value(networkInterfaces[0].networkIP)" 2>/dev/null)
if remoto vm-client "timeout 5 bash -c '</dev/tcp/$CARDS_IP/50052' 2>/dev/null && echo alcanca" | grep -q alcanca; then
  nao "a vm-client ALCANÇA o microsserviço — falta a regra deny-grpc-external"
else
  sim "a vm-client não alcança os microsserviços"
fi
if remoto vm-client "timeout 5 bash -c '</dev/tcp/$DB_IP/5432' 2>/dev/null && echo alcanca" | grep -q alcanca; then
  nao "a vm-client ALCANÇA o banco — falta a regra deny-postgres-external"
else
  sim "a vm-client não alcança o banco"
fi

echo
echo "== dados =="
linhas=$(remoto vm-db "sudo docker exec postgres psql -U expenses_app -d expenses -tAc 'SELECT count(*) FROM expenses'" | tr -d ' \r')
if [ -n "$linhas" ] && [ "$linhas" -gt 0 ] 2>/dev/null; then
  sim "$linhas gastos no banco"
else
  nao "banco vazio — rode: bash infra/semeia.sh"
fi

echo
echo "== fluxo ponta a ponta =="
EXTERNO=$(gcloud compute instances describe vm-client --zone="$ZONE" \
  --format="value(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null)
if [ -n "$EXTERNO" ]; then
  codigo=$(curl -s -o /dev/null -w "%{http_code}" -m 10 "http://$EXTERNO/" 2>/dev/null)
  [ "$codigo" = "200" ] && sim "a página carrega em http://$EXTERNO" || nao "a página devolveu $codigo"
  codigo=$(curl -s -o /dev/null -w "%{http_code}" -m 10 "http://$EXTERNO/api/expenses" 2>/dev/null)
  [ "$codigo" = "401" ] && sim "/api/expenses sem token devolve 401" || nao "/api/expenses devolveu $codigo, esperado 401"
else
  nao "a vm-client não tem IP externo"
fi

echo
echo "-------------------------------------------"
echo "  $ok ok, $falhou falha(s)"
[ "$falhou" -gt 0 ] && echo "  Veja a tabela de diagnóstico em docs/GCP-CONSOLE.md"
exit 0
