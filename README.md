# Expense tracking over gRPC

> **Integrantes:** Murilo Rodrigues, (preencher), (preencher)

Trabalho 1 de Sistemas Distribuídos — comunicação interna entre dois
microsserviços via **gRPC / Protocol Buffers**, rodando em duas VMs no **Google
Cloud Platform**, com regra de firewall VPC restringindo a porta de comunicação.

O usuário descreve um gasto em português ("gastei 89 reais num teclado no
crédito do Nubank"). O **Microsserviço A** usa a API da Anthropic para transformar isso
num comando estruturado e o envia por gRPC. O **Microsserviço B** valida,
persiste num PostgreSQL gerenciado (Cloud SQL) e responde.

> Código, identificadores e mensagens em inglês; comentários em português. A
> entrada em linguagem natural é em português, que é o domínio da aplicação.

## Arquitetura

```
                  vm-client                            vm-server
              (tag: grpc-client)                  (tag: grpc-server)
        ┌───────────────────────────┐        ┌──────────────────────────┐
        │   Microservice A          │        │   Microservice B         │
        │                           │        │                          │
 texto  │   client.py               │        │   server.py              │
 ─────► │     └─ nlu.py ──► Claude  │        │     └─ database.py ──────┼──┐
        │     └─ period.py          │        │                          │  │
        │                           │        │                          │  │
        │        gRPC stub ─────────┼───────►│ ── gRPC server :50051    │  │
        └───────────────────────────┘        └──────────────────────────┘  │
             10.128.0.3                            10.128.0.2              │
                              └──── VPC default ────┘                      │
                          firewall: tcp:50051, only 10.128.0.0/9,          │
                                only for tag grpc-server                   │
                                                                           │
                                   Cloud SQL (PostgreSQL) ◄────────────────┘
                                   banco-aula-sd · 10.115.48.3:5432
                                   IP privado apenas, via peering da VPC
```

### Banco de dados

Em produção o Microsserviço B usa um **Cloud SQL para PostgreSQL** com **IP
privado apenas** — o banco não tem endereço público; só máquinas dentro da VPC
`default` o alcançam, pelo peering de *Private Services Access*. É a mesma
filosofia da regra de firewall do gRPC: nada exposto à internet.

O `database.py` escolhe o backend pelo ambiente: com `PGHOST` definido, conecta
no PostgreSQL usando as variáveis padrão do libpq (`PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`); sem ele, usa um arquivo SQLite. O SQLite
fica para desenvolvimento local e para os testes — o Mac está fora da VPC e não
alcança o IP privado. As consultas são as mesmas nos dois; só o esquema da
coluna `id` e o driver mudam.

Os segredos ficam separados por VM: o `deploy.sh` envia só as variáveis `PG*`
para a `vm-server` (em `/opt/sd-gastos-grpc/server.env`, legível só por root) e
só a chave da LLM para a `vm-client`. Nenhuma das duas recebe o segredo que não
usa.

**A LLM vive inteiramente no Microsserviço A.** O B só conhece o contrato
`proto/expenses.proto` — não sabe que existe um modelo de linguagem. Trocar o
modelo por outro, ou por um formulário web, não muda uma linha do
servidor.

## Contrato

`proto/expenses.proto` define seis RPCs, sendo uma com *server-streaming*:

| RPC | Tipo | Para quê |
|---|---|---|
| `RegisterCard` | unário | cadastra a dupla (nome, método) |
| `ListCards` | unário | alimenta o prompt do modelo com cartões reais |
| `ValidateCard` | unário | verifica antes de agir; recusa cartão inventado |
| `RegisterExpense` | unário | grava a despesa |
| `SearchExpenses` | **streaming** | devolve os gastos um a um |
| `SummaryByGroup` | unário | totais por `category`, `card` ou `method` |

Um cartão é a dupla **(name, method)**: "Nubank credit" e "Nubank debit" são
registros distintos, o que permite responder "gastos do Nubank no crédito" sem
ambiguidade.

## Como o modelo é impedido de alucinar

Três camadas independentes, porque uma LLM erra e o sistema não pode gravar
lixo por causa disso:

1. **Restrição na entrada** — o cliente chama `ListCards` e injeta a lista real
   de cartões no prompt, junto com uma lista fechada de categorias.
2. **Verificação antes de agir** — se o comando cita um cartão, o cliente chama
   `ValidateCard` **antes** do RPC final. Se o cartão não existir, nada é
   gravado nem consultado (`difflib` no servidor resolve "Nubanck" → "Nubank").
3. **Garantia no banco** — a chave estrangeira composta em `expenses` recusa a
   escrita mesmo que as duas camadas acima falhem.

### Recuperação: recusar não é o fim

Quando a validação falha, o cliente não descarta o comando — oferece as saídas
possíveis e completa a operação com a escolha do usuário. Nenhum RPC novo é
necessário: as opções vêm do campo `suggestions` de `ValidateCardResponse`, e a
criação usa o `RegisterCard` que já existe.

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

Três situações distintas, com menus diferentes:

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

Este projeto usou o Gemini primeiro. A troca aconteceu por dois motivos
medidos, e vale registrar porque explicam decisões que ficaram no código:

- **O free tier do Gemini dá 20 requisições por dia**, por modelo e por projeto
  (`quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Uma tarde de
  testes esgotava a cota e a demonstração parava de funcionar.
- **A latência ficava entre 10 e 25 segundos** quando o serviço estava
  carregado. Ao vivo, esperar isso depois de cada frase digitada inviabiliza a
  apresentação.

Latência medida com o Haiku 4.5: **1,8 a 3,7 segundos** por comando, contra
~4 ms do salto gRPC. Vale mostrar isso na apresentação — o cliente imprime os
dois tempos lado a lado, e eles deixam claro que o gRPC não é o gargalo.

Custo: o prompt tem ~660 tokens de entrada e a resposta ~100 de saída, o que dá
**US$ 0,0012 por comando** no Haiku 4.5 (US$ 0,006 no Opus 5). O projeto
inteiro, incluindo ensaios, fica abaixo de um dólar.

Trocar o provedor mexeu apenas em `client/nlu.py`. O `.proto`, o servidor e o
resto do cliente não mudaram uma linha — nenhum deles sabe qual LLM está atrás.

## Rodando localmente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r client/requirements.txt
bash generate_stubs.sh
cp .env.example .env      # e preencha a ANTHROPIC_API_KEY
```

Em um terminal:

```bash
python server/server.py
```

Em outro:

```bash
python client/client.py --server localhost:50051
```

Sem chave de API, use `--offline`: um interpretador por regras locais que
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
| `:bytes` | mostra o protobuf serializado de cada requisição |
| `:cards` | lista os cartões cadastrados |
| `:clear` | limpa a tela |
| `:help` | exemplos de comandos |
| `:quit` | sai |

Por padrão a saída é limpa: só o resultado do comando. `:verbose` e `:bytes`
também têm as flags `--verbose` e `--bytes` para já iniciar ligados — é assim
que vale rodar na apresentação.

## Verificação

```bash
python client/period.py      # aritmética de datas, incluindo virada de ano
python server/test_server.py # os seis RPCs através de um canal gRPC real
```

O teste do servidor sobe um servidor numa porta efêmera e conversa com ele por
um canal de verdade — exercita a serialização e o transporte, não só as funções
Python.

## Deploy no GCP

```bash
cp infra/config.sh.example infra/config.sh   # edite o PROJECT
bash infra/setup_gcp.sh                      # VMs + regra de firewall
bash infra/deploy.sh                         # clona, instala e sobe
```

O `setup_gcp.sh` é idempotente. A regra de firewall criada é:

```
tcp:50051  ←  source-ranges 10.128.0.0/9  →  target-tags grpc-server
```

As duas restrições são o ponto: só tráfego de dentro da VPC, e só para a VM do
servidor. A porta não fica exposta à internet.

## Requisitos do trabalho

| Requisito | Onde é atendido |
|---|---|
| Definição do tema | Controle de gastos pessoais — este README e `proto/expenses.proto` |
| Contrato `.proto` com estruturas de dados e serviços RPC | `proto/expenses.proto`: 14 mensagens, 1 enum, 6 RPCs |
| Microsserviço A (cliente) envia requisição gRPC | `client/client.py` |
| Microsserviço B (servidor) processa e responde | `server/server.py` |
| Comunicação síncrona e eficiente | 5 RPCs unários bloqueantes + 1 server-streaming (`SearchExpenses`) |
| Regras de firewall VPC no GCP | `infra/setup_gcp.sh` — regra `allow-grpc-internal` |
| Infraestrutura em nuvem (GCP) | 2 VMs em `southamerica-east1-a`, criadas por `infra/setup_gcp.sh` |
| Código-fonte no GitHub | este repositório, com os dois microsserviços e o `.proto` |
| Troca de mensagens estruturadas e serializadas | `--bytes` / `:bytes` exibem o protobuf binário de cada requisição |

O enunciado pede **um** repositório contendo os arquivos `.proto` e o código dos
microsserviços. Microsserviço é sobre processos e máquinas separadas, não sobre
repositórios separados — e o `.proto` ser compartilhado pelos dois lados é
justamente o que torna o repositório único a escolha certa: em repositórios
distintos, o contrato dessincroniza.

## Estrutura

```
proto/expenses.proto   contrato compartilhado pelos dois serviços
generate_stubs.sh      gera os stubs (ficam fora do git)
server/                Microservice B: server.py, database.py, test_server.py
client/                Microservice A: client.py, nlu.py, period.py
infra/                 setup_gcp.sh, deploy.sh, expenses.service
```

Os stubs gerados não são versionados — `generate_stubs.sh` os recria. Isso
evita o problema clássico de stub dessincronizado do `.proto`.
