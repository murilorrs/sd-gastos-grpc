#!/usr/bin/env bash
# Espera o sistema subir e popula o banco com dados de demonstração.
#
#   bash infra/semeia.sh
#
# Roda tudo por dentro da vm-server, com curl em localhost:8000 — o Gateway
# não tem endereço público, e nem precisa ter.
#
# Pode rodar de novo: cartões repetidos devolvem 200 em vez de 201, e os
# gastos a mais só deixam o painel mais cheio.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
GATEWAY_USER="${GATEWAY_USER:-demo}"
GATEWAY_PASSWORD="${GATEWAY_PASSWORD:-}"

if [ -z "$GATEWAY_PASSWORD" ] && [ -f credenciais.txt ]; then
  GATEWAY_USER=$(awk '/^usuário/{print $2}' credenciais.txt)
  GATEWAY_PASSWORD=$(awk '/^senha  /{print $2}' credenciais.txt)
fi
[ -z "$GATEWAY_PASSWORD" ] && { echo "Defina GATEWAY_PASSWORD"; exit 1; }

gcloud config set project "$PROJECT" --quiet >/dev/null 2>&1

echo "esperando o Gateway responder (até 10 minutos)"
pronto=nao
for i in $(seq 1 60); do
  if gcloud compute ssh vm-server --zone="$ZONE" --quiet \
       --command "curl -s -m 5 localhost:8000/health" 2>/dev/null | grep -q '"ok"'; then
    pronto=sim; break
  fi
  printf "."; sleep 10
done
echo
[ "$pronto" = "nao" ] && {
  echo "O Gateway não respondeu. Veja: gcloud compute ssh vm-server --zone=$ZONE --command 'sudo journalctl -u gateway -n 50'"
  exit 1; }

# O roteiro roda inteiro dentro da VM: um SSH só, em vez de um por chamada.
LEITURA=$(cat <<'DENTRO'
set -euo pipefail
API=http://localhost:8000
T=$(curl -s $API/auth/token -H 'Content-Type: application/json' \
      -d "{\"username\":\"$GU\",\"password\":\"$GP\"}" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
A="Authorization: Bearer $T"; H="Content-Type: application/json"

cartao() { curl -s -o /dev/null -w "%{http_code} " -X POST $API/cards -H "$A" -H "$H" -d "$1"; }
gasto()  { curl -s -o /dev/null -w "%{http_code} " -X POST $API/expenses -H "$A" -H "$H" -d "$1"; }

echo -n "cartões:  "
cartao '{"name":"Nubank","method":"CREDIT"}'
cartao '{"name":"Nubank","method":"DEBIT"}'
cartao '{"name":"Itaú","method":"DEBIT"}'
cartao '{"name":"Inter","method":"CREDIT"}'
echo

# Datas espalhadas pelo mês corrente, para o painel ter o que desenhar em
# todos os gráficos e o filtro de período fazer diferença.
M=$(date +%Y-%m)
echo -n "gastos:   "
gasto "{\"product\":\"teclado mecânico\",\"amount\":389.90,\"card\":\"Nubank\",\"method\":\"CREDIT\",\"category\":\"technology\",\"date\":\"$M-03\"}"
gasto "{\"product\":\"almoço\",\"amount\":42.50,\"card\":\"Itaú\",\"method\":\"DEBIT\",\"category\":\"food\",\"date\":\"$M-05\"}"
gasto "{\"product\":\"corrida de app\",\"amount\":23.90,\"card\":\"Nubank\",\"method\":\"DEBIT\",\"category\":\"transport\",\"date\":\"$M-08\"}"
gasto "{\"product\":\"academia\",\"amount\":119.90,\"card\":\"Inter\",\"method\":\"CREDIT\",\"category\":\"health\",\"date\":\"$M-10\"}"
gasto "{\"product\":\"mercado\",\"amount\":312.40,\"card\":\"Nubank\",\"method\":\"CREDIT\",\"category\":\"food\",\"date\":\"$M-12\"}"
gasto "{\"product\":\"cinema\",\"amount\":58.00,\"card\":\"Itaú\",\"method\":\"DEBIT\",\"category\":\"leisure\",\"date\":\"$M-15\"}"
gasto "{\"product\":\"internet\",\"amount\":99.90,\"card\":\"Inter\",\"method\":\"CREDIT\",\"category\":\"housing\",\"date\":\"$M-18\"}"
gasto "{\"product\":\"fone bluetooth\",\"amount\":249.00,\"card\":\"Nubank\",\"method\":\"CREDIT\",\"category\":\"technology\",\"date\":\"$M-22\"}"
echo

echo -n "conferindo: "
curl -s $API/expenses -H "$A" \
  | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["expenses"]), "gastos no banco")'
DENTRO
)

gcloud compute ssh vm-server --zone="$ZONE" --quiet \
  --command "GU='$GATEWAY_USER' GP='$GATEWAY_PASSWORD' bash -s" <<< "$LEITURA"

echo
echo "pronto. O painel já abre com dados."
