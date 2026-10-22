# Expense tracking over gRPC

> **Integrantes:** Murilo Rodrigues, Caio Oliveira, (preencher)

Sistema de controle de gastos pessoais: interface web em React, API Gateway em
FastAPI, dois microsserviços gRPC e PostgreSQL. Cada serviço roda na sua
própria VM no Google Cloud — cinco ao todo, incluindo a do banco.

Trabalhos 1 e 2 de Sistemas Distribuídos.

## Arquitetura

```
   navegador          vm-client              vm-server
  ┌──────────┐    ┌──────────────┐     ┌──────────────────────┐
  │  React   │ :80│ nginx        │     │ API Gateway (FastAPI)│
  │  (SPA)   ├───►│  / → dist    │JSON │ 0.0.0.0:8000         │
  └──────────┘    │  /api ───────┼────►│  JWT · validação      │
                  └──────────────┘+JWT │  JSON ──► protobuf    │
                                       └────┬─────────────┬────┘
                                       gRPC │             │ gRPC
                                            ▼             ▼
                                      vm-cards        vm-expenses
                                    Cartões :50052 ◄── Gastos :50051
                                            │ ValidateCard │
                                            └──────┬───────┘
                                                   ▼
                                                 vm-db
                                        PostgreSQL (container) :5432
```

O frontend só fala com o Gateway. O Gateway autentica, valida e traduz para
gRPC. Cada microsserviço é dono de uma tabela e chega na do outro apenas pelo
contrato `.proto`. A única porta aberta para a internet é a 80 da `vm-client`.

**Firewall:**

```
      tcp:80     ←  0.0.0.0/0                      →  tag grpc-client
      tcp:8000   ←  10.128.0.0/9                   →  tag grpc-server
 800  tcp:5005x  ←  tags grpc-server, grpc-service →  tag grpc-service  allow
 900  tcp:5005x  ←  0.0.0.0/0                      →  tag grpc-service  deny
 800  tcp:5432   ←  tag grpc-service               →  tag db-server     allow
 900  tcp:5432   ←  0.0.0.0/0                      →  tag db-server     deny
```

Os pares 800/900 são o que mantém microsserviços e banco privados: a regra
`default-allow-internal` do GCP tem prioridade 65534 e nunca é alcançada.
Só os microsserviços falam com o banco — nem o Gateway alcança a porta 5432.

## API

| Método e rota | RPC | Sucesso |
|---|---|---|
| `POST /auth/token` | — | 200 |
| `GET /health` | — | 200 |
| `GET /meta` | — | 200 |
| `GET /cards` | `ListCards` | 200 |
| `POST /cards` | `RegisterCard` | 201, ou 200 se já existia |
| `GET /cards/validate` | `ValidateCard` | 200 |
| `POST /expenses` | `RegisterExpense` → `ValidateCard` | 201 |
| `GET /expenses` | `SearchExpenses` (stream) | 200 |
| `GET /expenses/summary` | `SummaryByGroup` | 200 |
| `PUT /expenses/{id}` | `UpdateExpense` → `ValidateCard` | 200 |
| `DELETE /expenses/{id}` | `DeleteExpense` | 200 |
| `POST /nlu/interpret` | o RPC que o comando pedir | 200 |

Toda rota exceto `/auth/token` e `/health` exige `Authorization: Bearer`.
Sem token: **401**. Payload inválido: **400**. Documentação interativa em
`/docs`.

Cada requisição recebe um id, enviado na metadata de toda chamada gRPC e
devolvido no cabeçalho `X-Request-Id`. As três VMs logam a mesma operação com
o mesmo id.

## Rodando localmente

Com Docker, o sistema inteiro contra um PostgreSQL de verdade:

```bash
docker compose up --build
# http://localhost:8080 — usuário demo, senha demo-password
```

Sem Docker:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt -r gateway/requirements.txt -r client/requirements.txt
bash generate_stubs.sh
cp .env.example .env          # preencha JWT_SECRET, GATEWAY_USER, GATEWAY_PASSWORD

bash run_backend.sh           # backend com SQLite em data/
cd web && npm install && npm run dev    # http://localhost:5173
```

## Testes

```bash
python language/period.py
python server/test_services.py
python gateway/test_gateway.py
cd web && npx tsc --noEmit
```

Os testes de serviço sobem os microsserviços em portas efêmeras e conversam
por canais gRPC reais, incluindo o caso em que o serviço de Cartões cai.

## Deploy

Um script provisiona tudo — VMs, firewall, banco — e semeia os dados de
demonstração: [`docs/DEPLOY.md`](docs/DEPLOY.md).

```bash
gcloud auth login
PROJECT=seu-projeto bash infra/provision_gcp.sh   # cria tudo e semeia
bash infra/verifica.sh                            # 18 checagens
```

O caminho manual, clicando no console, está em
[`docs/GCP-CONSOLE.md`](docs/GCP-CONSOLE.md). Os scripts
`infra/startup-*.sh` são feitos para colar no campo "Script de inicialização"
da VM.

A ordem importa: `vm-db` → `vm-cards` → `vm-expenses` → `vm-server` →
`vm-client`. Cada uma precisa do IP interno da anterior.

## Estrutura

```
proto/expenses.proto     contrato: CardService e ExpenseService
gateway/                 API Gateway (FastAPI)
server/                  microsserviços de Cartões e de Gastos
language/                interpretação de linguagem natural
client/                  cliente de terminal
web/                     frontend React
infra/                   scripts de deploy, nginx e units do systemd
docs/                    DEPLOY.md, GCP-CONSOLE.md e APRESENTACAO.md
```

Os stubs gerados não são versionados; `generate_stubs.sh` os recria.

## Configuração

| Variável | Onde | Para quê |
|---|---|---|
| `PGHOST` … `PGSSLMODE` | microsserviços | conexão com o PostgreSQL da `vm-db` |
| `CARDS_ADDR`, `EXPENSES_ADDR` | Gateway, Gastos | endereço dos microsserviços |
| `GRPC_HOST` | microsserviços | interface de escuta |
| `JWT_SECRET` | Gateway | assinatura dos tokens |
| `GATEWAY_USER`, `GATEWAY_PASSWORD` | Gateway | login aceito |
| `ANTHROPIC_API_KEY` | Gateway | opcional; sem ela, interpretação por regras |

Sem `PGHOST`, os microsserviços usam SQLite em `data/`.
