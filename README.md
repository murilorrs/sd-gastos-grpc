# Controle de gastos com gRPC

Trabalho 1 de Sistemas Distribuídos — comunicação interna entre dois
microsserviços via **gRPC / Protocol Buffers**, rodando em duas VMs no **Google
Cloud Platform**, com regra de firewall VPC restringindo a porta de comunicação.

O usuário descreve um gasto em português ("gastei 89 reais num teclado no
crédito do Nubank"). O **Microsserviço A** usa o Gemini para transformar isso
num comando estruturado e o envia por gRPC. O **Microsserviço B** valida,
persiste num SQLite e responde.

## Arquitetura

```
                 vm-cliente                          vm-servidor
              (tag: grpc-client)                  (tag: grpc-server)
        ┌───────────────────────────┐        ┌──────────────────────────┐
        │   Microsserviço A         │        │   Microsserviço B        │
        │                           │        │                          │
 texto  │   client.py               │        │   server.py              │
 ─────► │     └─ nlu.py ──► Gemini  │        │     └─ db.py ──► SQLite  │
        │     └─ periodo.py         │        │                          │
        │                           │        │                          │
        │        stub gRPC ─────────┼───────►│ ── servidor gRPC :50051  │
        └───────────────────────────┘        └──────────────────────────┘
             10.158.0.x                            10.158.0.y
                              └──── VPC default ────┘
                          firewall: tcp:50051, apenas 10.128.0.0/9,
                                apenas para a tag grpc-server
```

**A LLM vive inteiramente no Microsserviço A.** O B só conhece o contrato
`proto/gastos.proto` — não sabe que existe um modelo de linguagem. Trocar o
Gemini por outro modelo, ou por um formulário web, não muda uma linha do
servidor.

## Contrato

`proto/gastos.proto` define seis RPCs, sendo uma com *server-streaming*:

| RPC | Tipo | Para quê |
|---|---|---|
| `RegistrarCartao` | unário | cadastra a dupla (nome, método) |
| `ListarCartoes` | unário | alimenta o prompt do modelo com cartões reais |
| `ValidarCartao` | unário | verifica antes de agir; recusa cartão inventado |
| `RegistrarGasto` | unário | grava a despesa |
| `BuscarGastos` | **streaming** | devolve os gastos um a um |
| `ResumoPorGrupo` | unário | totais por categoria, cartão ou método |

Um cartão é a dupla **(nome, método)**: "Nubank crédito" e "Nubank débito" são
registros distintos, o que permite responder "gastos do Nubank no crédito" sem
ambiguidade.

## Como o modelo é impedido de alucinar

Três camadas independentes, porque uma LLM erra e o sistema não pode gravar
lixo por causa disso:

1. **Restrição na entrada** — o cliente chama `ListarCartoes` e injeta a lista
   real de cartões no prompt, junto com uma lista fechada de categorias.
2. **Verificação antes de agir** — se o comando cita um cartão, o cliente chama
   `ValidarCartao` **antes** do RPC final. Se o cartão não existir, nada é
   gravado nem consultado, e o usuário vê sugestões (`difflib` resolve
   "Nubanck" → "Nubank").
3. **Garantia no banco** — a chave estrangeira composta em `gastos` recusa a
   escrita mesmo que as duas camadas acima falhem.

Datas seguem a mesma lógica: o modelo devolve um **rótulo** (`este_mes`,
`ontem`), e quem calcula o intervalo é o `datetime` em `cliente/periodo.py`.
Modelos erram aritmética de data, e aqui o erro seria silencioso.

## Rodando localmente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r cliente/requirements.txt
bash gerar_stubs.sh
cp .env.example .env      # e preencha a GEMINI_API_KEY
```

Em um terminal:

```bash
python servidor/server.py
```

Em outro:

```bash
python cliente/client.py --servidor localhost:50051
```

Sem chave do Gemini, use `--offline`: um interpretador por regras locais que
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

Dentro do REPL: `:ajuda`, `:cartoes`, `:bytes` (liga a exibição do protobuf
serializado), `:sair`.

## Verificação

```bash
python cliente/periodo.py      # aritmética de datas, incluindo virada de ano
python servidor/test_server.py # os seis RPCs através de um canal gRPC real
```

O teste do servidor sobe um servidor numa porta efêmera e conversa com ele por
um canal de verdade — exercita a serialização e o transporte, não só as funções
Python.

## Deploy no GCP

```bash
cp infra/config.sh.example infra/config.sh   # edite o PROJETO
bash infra/setup_gcp.sh                      # VMs + regra de firewall
bash infra/deploy.sh                         # clona, instala e sobe
```

O `setup_gcp.sh` é idempotente. A regra de firewall criada é:

```
tcp:50051  ←  source-ranges 10.128.0.0/9  →  target-tags grpc-server
```

As duas restrições são o ponto: só tráfego de dentro da VPC, e só para a VM do
servidor. A porta não fica exposta à internet.

## Estrutura

```
proto/gastos.proto     contrato compartilhado pelos dois serviços
gerar_stubs.sh         gera os stubs (ficam fora do git)
servidor/              Microsserviço B: server.py, db.py, test_server.py
cliente/               Microsserviço A: client.py, nlu.py, periodo.py
infra/                 setup_gcp.sh, deploy.sh, gastos.service
```

Os stubs gerados não são versionados — `gerar_stubs.sh` os recria. Isso evita
o problema clássico de stub dessincronizado do `.proto`.
