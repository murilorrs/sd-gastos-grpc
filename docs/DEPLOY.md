# Subindo o sistema no Google Cloud

Um script faz o provisionamento inteiro, do projeto vazio até a interface no
ar com dados. Este documento é para quem vai rodá-lo — não é preciso conhecer
o projeto.

Quem prefere clicar no console tem o caminho manual em
[`GCP-CONSOLE.md`](GCP-CONSOLE.md).

## O que vai ser criado

Cinco VMs `e2-small` e seis regras de firewall, numa zona só:

| VM | O que roda | IP externo |
|---|---|---|
| `vm-db` | PostgreSQL 16 em container | não |
| `vm-cards` | microsserviço de Cartões (gRPC :50052) | não |
| `vm-expenses` | microsserviço de Gastos (gRPC :50051) | não |
| `vm-server` | API Gateway (HTTP :8000) | não |
| `vm-client` | nginx :80 com o frontend | **sim** |

Só a `vm-client` é alcançável da internet. O Gateway responde apenas de dentro
da VPC, os microsserviços apenas ao Gateway e um ao outro, e o banco apenas
aos dois microsserviços.

**Custo:** cinco `e2-small` ligadas dão algo em torno de US$ 0,07/hora no
total. Pare tudo depois de usar — tem um comando pronto no fim deste
documento.

## Antes de rodar

Três coisas, e só a última costuma faltar:

1. **`gcloud` instalado** — `gcloud version`
2. **Autenticado** — `gcloud auth login` (abre o navegador)
3. **Uma conta de faturamento ativa** na sua conta Google

O script vincula o faturamento ao projeto sozinho, desde que exista uma conta
aberta. O que ele não faz é criar a conta de faturamento — isso exige cartão e
é uma vez só, no console.

Para conferir que você tem uma:

```bash
gcloud billing accounts list
```

Se a lista vier vazia, crie em **console.cloud.google.com → Faturamento**.

## Rodando

```bash
git clone https://github.com/murilorrs/sd-gastos-grpc.git
cd sd-gastos-grpc

PROJECT=o-id-do-seu-projeto bash infra/provision_gcp.sh
```

O `PROJECT` é o **ID** do projeto, não o nome de exibição —
`gcloud projects list` mostra os dois.

Variáveis opcionais, todas com padrão:

| Variável | Padrão | Para quê |
|---|---|---|
| `REGION` | `us-central1` | onde criar tudo |
| `ZONE` | `$REGION-a` | zona das VMs |
| `MACHINE_TYPE` | `e2-small` | tamanho das VMs |
| `BILLING_ACCOUNT` | a primeira aberta | se você tiver mais de uma |
| `ANTHROPIC_API_KEY` | vazio | liga a interpretação por IA do assistente |
| `REPO_URL` | o repositório do grupo | de onde as VMs clonam |

Exemplo com tudo:

```bash
PROJECT=sd-2026 REGION=southamerica-east1 ANTHROPIC_API_KEY=sk-ant-... \
  bash infra/provision_gcp.sh
```

## O que esperar

De 10 a 15 minutos, nesta ordem:

```
=====> faturamento          vincula se preciso          ~30s
=====> APIs                 ativa o Compute Engine      ~1min
=====> firewall             seis regras                 ~30s
=====> vm-db                postgres em container       ~20s para criar
=====> vm-cards                                         ~20s
=====> vm-expenses                                      ~20s
=====> vm-server                                        ~20s
=====> vm-client                                        ~20s
=====> esperando o sistema subir e semeando             3 a 8 min
```

As VMs são criadas rápido; o tempo está nos scripts de inicialização que
rodam dentro delas — instalar dependências, gerar os stubs do gRPC e, na
`vm-client`, compilar o frontend. O script espera por isso antes de semear.

No fim ele imprime:

```
=====> pronto

  Interface web:  http://34.XX.XX.XX
  Login:          demo / <senha gerada>
```

e grava as mesmas informações em `credenciais.txt`, que fica fora do git.
**Esse arquivo tem senhas** — não mande em grupo.

Logo depois ele semeia 4 cartões e 8 gastos e roda a verificação sozinho, para
a interface não abrir vazia.

## Conferindo

```bash
bash infra/verifica.sh
```

São 18 checagens: VMs ligadas, serviços ativos, o Gateway respondendo, a
`vm-expenses` alcançando a `vm-cards` e o banco, dados gravados, a página
carregando e `/api/expenses` sem token devolvendo 401.

Duas delas verificam o que **não** pode funcionar: a `vm-client` não pode
alcançar nem os microsserviços nem o banco. Se passarem, falta regra de
firewall.

Saída esperada no fim:

```
  18 ok, 0 falha(s)
```

Se o banco aparecer vazio, rode `bash infra/semeia.sh`.

## Se algo falhar

O script é **idempotente**: rodar de novo reaproveita o que já existe e só
refaz o que faltou. Em quase todo erro, a resposta é rodar de novo.

| Mensagem | O que é |
|---|---|
| `requires billing to be enabled` | o faturamento não propagou ainda; espere 2 min e rode de novo |
| `Nenhuma conta de faturamento aberta` | crie uma no console |
| o script passa mas a `verifica.sh` acusa serviço fora | o script de inicialização ainda está rodando; espere e rode a verificação de novo |
| `gateway fora` depois de 10 min | `gcloud compute ssh vm-server --zone=ZONA --command "sudo journalctl -u gateway -n 50"` |
| tudo no ar, mas gasto não grava | a `vm-expenses` não alcança o banco ou a `vm-cards`; veja o log dela |

Os logs de inicialização de qualquer VM:

```bash
gcloud compute ssh vm-db --zone=us-central1-a \
  --command "sudo journalctl -u google-startup-scripts -n 60"
```

## Depois de mexer no código

As VMs clonam o repositório ao subir, então código novo exige um `git pull`
dentro delas:

```bash
Z=us-central1-a
for vm in vm-cards vm-expenses; do
  gcloud compute ssh $vm --zone=$Z --command "
    cd /opt/sd-gastos-grpc && sudo git pull &&
    sudo PATH=/opt/sd-gastos-grpc/.venv/bin:\$PATH bash generate_stubs.sh &&
    sudo systemctl restart \$(basename $vm | sed 's/vm-//')"
done
gcloud compute ssh vm-server --zone=$Z --command "
  cd /opt/sd-gastos-grpc && sudo git pull &&
  sudo PATH=/opt/sd-gastos-grpc/.venv/bin:\$PATH bash generate_stubs.sh &&
  sudo systemctl restart gateway"
gcloud compute ssh vm-client --zone=$Z --command "
  cd /opt/sd-gastos-grpc && sudo git pull &&
  cd web && npm ci && npm run build && sudo systemctl reload nginx"
```

Mexeu no `.proto`? As três VMs de backend precisam do `generate_stubs.sh` e do
restart. Stub velho de um lado e novo do outro aparece como campo chegando
vazio, sem erro nenhum — é o problema mais chato de achar.

## Parando e apagando

**Parar** preserva os dados e para a cobrança das VMs:

```bash
gcloud compute instances stop vm-db vm-cards vm-expenses vm-server vm-client \
  --zone=us-central1-a
```

> Ao religar, os IPs internos podem mudar. Nesse caso rode
> `bash infra/provision_gcp.sh` de novo: ele detecta as VMs existentes e
> não recria nada, mas também não reescreve os endereços. O caminho seguro é
> apagar e recriar, que leva os mesmos 15 minutos.

**Apagar** remove tudo:

```bash
gcloud compute instances delete vm-db vm-cards vm-expenses vm-server vm-client \
  --zone=us-central1-a --quiet
gcloud compute firewall-rules delete allow-web-external allow-gateway-internal \
  allow-grpc-internal deny-grpc-external allow-postgres-internal \
  deny-postgres-external --quiet
gcloud compute routers delete nat-router --region=us-central1 --quiet
```

## Rodando sem nuvem nenhuma

Para desenvolver, ou como plano B:

```bash
docker compose up --build
# http://localhost:8080 — usuário demo, senha demo-password
```

É a mesma topologia, um container por VM, com PostgreSQL de verdade.
