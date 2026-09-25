# Expense tracking over gRPC

> **Integrantes:** Murilo Rodrigues, (preencher), (preencher)

Trabalhos 1 e 2 de Sistemas Distribuídos — um sistema de controle de gastos com
**API Gateway (FastAPI)**, **dois microsserviços gRPC** e **PostgreSQL** (Cloud
SQL), rodando em duas VMs no **Google Cloud Platform**.

O usuário descreve um gasto em português ("gastei 89 reais num teclado no
crédito do Nubank"). O cliente usa a API da Anthropic para transformar a frase
num comando estruturado e o envia ao **Gateway** por HTTP/JSON, com um token
JWT. O Gateway valida, traduz para **gRPC/protobuf** e despacha para o
microsserviço dono do dado — **Cartões** ou **Gastos** — que persiste no banco.

> Código, identificadores e mensagens em inglês; comentários em português. A
> entrada em linguagem natural é em português, que é o domínio da aplicação.

## Arquitetura

```
              vm-client (10.128.0.3)                     vm-server (10.128.0.2)
        ┌──────────────────────────────┐   HTTP/JSON  ┌────────────────────────────────┐
 texto  │ client.py                    │   + JWT      │ API Gateway (FastAPI)          │
 ─────► │   └─ nlu.py ──► Claude       ├─────────────►│ 0.0.0.0:8000                   │
        │   └─ period.py               │              │   valida (400) · JWT (401)     │
        └──────────────────────────────┘              │   JSON ──► protobuf            │
                                                      │        │ gRPC        │ gRPC    │
                                  firewall:           │        ▼             ▼         │
                        tcp:8000 · só 10.128.0.0/9    │  Cartões        Gastos         │
                        · só tag grpc-server          │  127.0.0.1:50052  127.0.0.1:50051
                                                      │        ▲    gRPC     │         │
                                                      │        └─────────────┘         │
                                                      └────────┬───────────────┬───────┘
                                                               │  cards        │ expenses
                                                               ▼               ▼
                                                      Cloud SQL (PostgreSQL) banco-aula-sd
                                                      10.115.48.3:5432 · IP privado, via peering
```

Quatro saltos, cada um com um protocolo e um motivo:

1. **Cliente → Gateway: HTTP/JSON com JWT.** É a única porta de entrada. O
   Gateway escuta em `0.0.0.0:8000`; todo o resto da `vm-server` escuta só em
   `127.0.0.1`.
2. **Gateway → microsserviços: gRPC/protobuf.** O Gateway desserializa o JSON,
   valida, e serializa em protobuf para o serviço dono do dado.
3. **Gastos → Cartões: gRPC.** Antes de gravar um gasto, o serviço de Gastos
   pergunta ao de Cartões se o cartão existe. É a comunicação entre
   microsserviços do sistema.
4. **Microsserviços → Cloud SQL: PostgreSQL**, pela rede privada. Cada serviço
   só toca a sua tabela.

**Por que os serviços gRPC escutam só em 127.0.0.1.** O enunciado exige que o
cliente nunca fale direto com os microsserviços. Firewall não garantiria isso: a
regra `default-allow-internal` do GCP libera todas as portas entre VMs da VPC.
Escutando só na interface local, os serviços são inalcançáveis de fora da
`vm-server` — qualquer que seja a regra de firewall.

**A LLM vive no cliente.** O Gateway e os microsserviços recebem JSON e
protobuf já estruturados; nenhum deles sabe que existe um modelo de linguagem.

### Banco de dados

Em produção os microsserviços usam um **Cloud SQL para PostgreSQL** com **IP
privado apenas** — o banco não tem endereço público; só máquinas dentro da VPC
`default` o alcançam, pelo peering de *Private Services Access*.

Cada microsserviço é dono de uma tabela: Cartões tem `cards`, Gastos tem
`expenses`. Não há chave estrangeira entre elas — ela acoplaria os dois
serviços por baixo do contrato. O serviço de Gastos só sabe se um cartão existe
perguntando ao de Cartões via gRPC, e grava com a grafia que ele devolve.

O `database.py` escolhe o backend pelo ambiente: com `PGHOST` definido, conecta
no PostgreSQL usando as variáveis padrão do libpq (`PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`); sem ele, usa arquivos SQLite em `data/`.
O SQLite fica para desenvolvimento local e para os testes — o Mac está fora da
VPC e não alcança o IP privado. As consultas são as mesmas nos dois.

Os segredos ficam separados por VM. O `deploy.sh` envia para a `vm-server` a
senha do banco e o segredo do JWT (em `/opt/sd-gastos-grpc/server.env`,
legível só por root), e para a `vm-client` a chave da LLM e o login do
Gateway. Nenhuma das duas recebe o segredo que não usa.

## API Gateway

| Método e rota | Microsserviço | Sucesso |
|---|---|---|
| `POST /auth/token` | — (emite o JWT) | 200 |
| `GET /cards` | Cartões · `ListCards` | 200 |
| `POST /cards` | Cartões · `RegisterCard` | **201**, ou 200 se já existia |
| `GET /cards/validate` | Cartões · `ValidateCard` | 200 |
| `POST /expenses` | Gastos · `RegisterExpense` (→ Cartões · `ValidateCard`) | **201** |
| `GET /expenses` | Gastos · `SearchExpenses` (stream) | 200 |
| `GET /expenses/summary` | Gastos · `SummaryByGroup` | 200 |
| `GET /health` | — | 200 |

Documentação interativa, gerada pelo FastAPI, em `http://<gateway>:8000/docs`.

**Autenticação.** Toda rota exceto `/auth/token` e `/health` exige
`Authorization: Bearer <token>`. Sem token, com token inválido ou vencido
(uma hora), a resposta é **401** — antes de qualquer chamada gRPC.

**Validação.** Os corpos e parâmetros são declarados como modelos Pydantic:
campos obrigatórios, `amount > 0`, `method` só `CREDIT` ou `DEBIT`, categoria
de uma lista fechada, datas no formato `AAAA-MM-DD`. Qualquer violação, e JSON
malformado, resulta em **400** (o FastAPI usaria 422 por padrão; o enunciado
pede 400). Um cartão inexistente também é 400 — quem diz isso é o serviço de
Cartões, consultado pelo de Gastos.

```bash
TOKEN=$(curl -s localhost:8000/auth/token -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"..."}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -i localhost:8000/expenses                                   # 401
curl -i localhost:8000/expenses -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"product":"x","amount":0}' -X POST   # 400
```

## Contrato

`proto/expenses.proto` define dois serviços, que compartilham as mensagens:

| Serviço | RPC | Tipo | Para quê |
|---|---|---|---|
| `CardService` | `RegisterCard` | unário | cadastra a dupla (nome, método) |
| | `ListCards` | unário | alimenta o prompt do modelo com cartões reais |
| | `ValidateCard` | unário | confere um cartão e devolve a grafia cadastrada |
| `ExpenseService` | `RegisterExpense` | unário | grava o gasto, depois de consultar o `CardService` |
| | `SearchExpenses` | **streaming** | devolve os gastos um a um |
| | `SummaryByGroup` | unário | totais por `category`, `card` ou `method` |

Um cartão é a dupla **(name, method)**: "Nubank credit" e "Nubank debit" são
registros distintos, o que permite responder "gastos do Nubank no crédito" sem
ambiguidade.

## Como o modelo é impedido de alucinar

Três camadas independentes, porque uma LLM erra e o sistema não pode gravar
lixo por causa disso:

1. **Restrição na entrada** — o cliente busca a lista real de cartões e a
   injeta no prompt, junto com uma lista fechada de categorias.
2. **Verificação antes de agir** — se o comando cita um cartão, o cliente
   consulta `GET /cards/validate` **antes** de gravar ou buscar. Se o cartão não
   existir, oferece corrigir (`difflib` no serviço de Cartões resolve
   "Nubanck" → "Nubank").
3. **Garantia no backend** — mesmo que as duas camadas acima falhem, o Gateway
   recusa categoria fora da lista, e o serviço de Gastos recusa gravar se o de
   Cartões não confirmar o cartão. Se o serviço de Cartões estiver fora do ar,
   Gastos recusa em vez de gravar às cegas.

### Recuperação: recusar não é o fim

Quando a validação falha, o cliente não descarta o comando — oferece as saídas
possíveis e completa a operação com a escolha do usuário. As opções vêm do
campo `suggestions` da validação, e a criação usa o `POST /cards`.

```
> gastei 55 reais no crédito do Itaú
  x card Itau is registered, but not for credit (only: debit)
  how do you want to proceed?
    1) use Itau (debit)
    2) register Itau for credit and record it there
    0) cancel
  choice> 2
  + Itau (credit) registered
  + #3  expense  55.00  Itau/credit
```

| Situação | O que é oferecido |
|---|---|
| Cartão não existe, num registro | usar um cadastrado, ou cadastrar o novo e lançar nele |
| Cartão não existe, numa consulta | apenas os cartões cadastrados (não faz sentido criar) |
| Método não informado, num registro | crédito ou débito — mas só se o cartão tiver os dois |

Cancelar não grava nada. Sem terminal interativo (entrada redirecionada), o
menu cancela em vez de executar o comando pela metade.

### Datas

O modelo devolve um **rótulo** (`this_month`, `yesterday`), e quem calcula o
intervalo é o `datetime` em `client/period.py`. Modelos erram aritmética de
data, e aqui o erro seria silencioso.

Duas defesas concretas nasceram de erros observados em teste, não de suposição:

- O modelo devolveu `last_month` como data de uma transação, um rótulo de
  período onde se esperava um único dia. Cair para "hoje" gravaria a data
  errada em silêncio, então `transaction_date` resolve o período para o seu
  último dia, limitado a hoje.
- O modelo colocou o tempo no campo `period` em vez de `date_label` num
  registro. O cliente aceita os dois nomes: depender do modelo acertar o nome
  do campo é frágil demais para um dado que ninguém confere.

## Configuração da LLM

```
ANTHROPIC_API_KEY=...     # console.anthropic.com -> API keys
ANTHROPIC_MODEL=claude-haiku-4-5
ANTHROPIC_TIMEOUT=30
```

A chave sai em `console.anthropic.com` e exige créditos em Billing (pré-pago,
mínimo US$ 5). Liste os modelos da conta com `python client/nlu.py --models`.

Este projeto usou o Gemini primeiro e migrou por dois motivos medidos: o free
tier dava **20 requisições por dia** por modelo, e a latência ficava entre **10
e 25 segundos** com o serviço carregado. Com o Haiku 4.5 a interpretação leva
**1,8 a 3,7 segundos**, e custa cerca de **US$ 0,0012 por comando**. A troca
mexeu apenas em `client/nlu.py`.

## Rodando localmente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt -r gateway/requirements.txt -r client/requirements.txt
bash generate_stubs.sh
cp .env.example .env      # preencha ANTHROPIC_API_KEY, JWT_SECRET, GATEWAY_USER, GATEWAY_PASSWORD
```

Em um terminal, o backend inteiro — os dois microsserviços e o Gateway, com
SQLite em `data/`:

```bash
bash run_backend.sh
```

Em outro, o cliente:

```bash
python client/client.py --verbose
```

Sem chave da Anthropic, use `--offline`: um interpretador por regras locais que
cobre os comandos do roteiro de demonstração.

### Comandos de exemplo

```
cadastra o Nubank no crédito e no débito, e o Itaú no débito
gastei 89 reais num teclado mecânico no crédito do Nubank
almoço de 42 reais no débito do Itaú ontem
me mostra tudo que eu gastei no Nubank no crédito esse mês
quanto gastei em tecnologia?
resumo por método
```

Dentro do REPL:

| Comando | O que faz |
|---|---|
| `:verbose` | mostra o comando estruturado que a LLM devolveu e os tempos de cada etapa |
| `:bytes` | mostra a requisição HTTP e o JSON enviado ao Gateway |
| `:cards` | lista os cartões cadastrados |
| `:clear` | limpa a tela |
| `:help` | exemplos de comandos |
| `:quit` | sai |

`:verbose` e `:bytes` também têm as flags `--verbose` e `--bytes`. O outro lado
da tradução — o tamanho do protobuf que o Gateway monta a partir do JSON —
aparece no log do Gateway, em linhas como
`RegisterExpense  JSON -> protobuf 114 bytes`.

## Verificação

```bash
python client/period.py          # aritmética de datas, incluindo virada de ano
python server/test_services.py   # os dois microsserviços por canais gRPC reais
python gateway/test_gateway.py   # 401, 400, 201 e a tradução JSON -> gRPC
```

Os testes sobem os serviços em portas efêmeras e conversam com eles por canais
de verdade — exercitam serialização e transporte, não só as funções Python. O
de serviços inclui o caso em que Cartões cai e Gastos precisa recusar.

## Deploy no GCP

```bash
cp infra/config.sh.example infra/config.sh   # edite o PROJECT
bash infra/setup_gcp.sh                      # VMs + regra de firewall
bash infra/deploy.sh                         # clona, instala e sobe
```

Na `vm-server` sobem três serviços do systemd — `cards`, `expenses` e
`gateway` — que voltam sozinhos se a VM reiniciar. Para acompanhar os três
juntos:

```bash
sudo journalctl -u gateway -u cards -u expenses -f
```

A regra de firewall criada pelo `setup_gcp.sh`:

```
tcp:8000  ←  source-ranges 10.128.0.0/9  →  target-tags grpc-server
```

Só tráfego de dentro da VPC, e só para a VM do servidor. Nada fica exposto à
internet — nem o Gateway, nem o banco.

## Requisitos do Trabalho 2

| Requisito | Onde é atendido |
|---|---|
| Frontend que fala só com o Gateway | `client/client.py` — HTTP/JSON para o Gateway; os serviços gRPC nem aceitam conexão de fora da `vm-server` |
| API Gateway com framework web | `gateway/app.py` — FastAPI, ponto único de entrada |
| Mínimo de 2 microsserviços gRPC | `server/cards_service.py` e `server/expenses_service.py` |
| Comunicação entre microsserviços via gRPC | Gastos chama `CardService.ValidateCard` antes de gravar |
| Banco de dados real | Cloud SQL PostgreSQL; todas as operações leem e gravam nele |
| Validação no Gateway: 400 / 201 | modelos Pydantic + tratador de `RequestValidationError`; `POST` retorna 201 |
| JWT no Gateway: 401 | dependência `require_token` em todas as rotas de negócio |
| Tradução JSON → gRPC/protobuf | função `call` do Gateway, que registra o tamanho do protobuf de cada chamada |

## Requisitos do Trabalho 1

| Requisito | Onde é atendido |
|---|---|
| Contrato `.proto` com estruturas de dados e serviços RPC | `proto/expenses.proto` |
| Comunicação síncrona e eficiente | RPCs unários + 1 server-streaming (`SearchExpenses`) |
| Regras de firewall VPC no GCP | `infra/setup_gcp.sh` |
| Infraestrutura em nuvem (GCP) | 2 VMs em `us-central1-c` + Cloud SQL |
| Código-fonte no GitHub | este repositório |

O enunciado pede **um** repositório contendo os arquivos `.proto` e o código dos
microsserviços. Microsserviço é sobre processos separados, não sobre
repositórios separados — e o `.proto` ser compartilhado por todos os lados é
justamente o que torna o repositório único a escolha certa: em repositórios
distintos, o contrato dessincroniza.

## Estrutura

```
proto/expenses.proto     contrato: CardService e ExpenseService
generate_stubs.sh        gera os stubs para server/ e gateway/ (fora do git)
run_backend.sh           sobe o backend local: os dois serviços e o Gateway
gateway/                 API Gateway: app.py, test_gateway.py
server/                  microsserviços: cards_service.py, expenses_service.py,
                         common.py, database.py, test_services.py
client/                  cliente de terminal: client.py, nlu.py, period.py
infra/                   setup_gcp.sh, deploy.sh e as units do systemd
                         (cards, expenses, gateway)
```

Os stubs gerados não são versionados — `generate_stubs.sh` os recria. Isso
evita o problema clássico de stub dessincronizado do `.proto`.
