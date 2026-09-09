# Expense tracking over gRPC

Trabalho 1 de Sistemas Distribuídos — comunicação interna entre dois
microsserviços via **gRPC / Protocol Buffers**, rodando em duas VMs no **Google
Cloud Platform**, com regra de firewall VPC restringindo a porta de comunicação.

O usuário descreve um gasto em português ("gastei 89 reais num teclado no
crédito do Nubank"). O **Microsserviço A** usa o Gemini para transformar isso
num comando estruturado e o envia por gRPC. O **Microsserviço B** valida,
persiste num SQLite e responde.

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
 ─────► │     └─ nlu.py ──► Gemini  │        │     └─ database.py ──►   │
        │     └─ period.py          │        │            SQLite        │
        │                           │        │                          │
        │        gRPC stub ─────────┼───────►│ ── gRPC server :50051    │
        └───────────────────────────┘        └──────────────────────────┘
             10.158.0.x                            10.158.0.y
                              └──── VPC default ────┘
                          firewall: tcp:50051, only 10.128.0.0/9,
                                only for tag grpc-server
```

**A LLM vive inteiramente no Microsserviço A.** O B só conhece o contrato
`proto/expenses.proto` — não sabe que existe um modelo de linguagem. Trocar o
Gemini por outro modelo, ou por um formulário web, não muda uma linha do
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

## Configuração do Gemini

```
GEMINI_MODEL=gemini-3.6-flash
GEMINI_MODEL_FALLBACK=gemini-3.5-flash-lite
GEMINI_TIMEOUT_MS=15000
```

Três coisas descobertas ao integrar, todas relevantes no dia da apresentação:

- **Modelos somem.** O `gemini-2.5-flash` responde 404 para contas novas
  ("no longer available to new users"). Confira o que a sua conta enxerga com
  `python client/nlu.py --models` antes de apresentar.
- **O free tier limita a 20 requisições por minuto**, por modelo. Um humano
  digitando não chega perto disso; uma bateria de testes chega. Ao estourar, a
  chamada é redirecionada ao modelo reserva, que tem cota própria.
- **503 por alta demanda acontece.** Sem o `GEMINI_TIMEOUT_MS`, o SDK faz
  backoff sozinho e uma chamada pode passar de um minuto. Com ele, a tentativa
  é abortada e o código passa para o reserva e, se preciso, para o modo
  offline — que avisa na tela e completa o comando mesmo assim.

Latência típica medida: **3 a 7 segundos** por comando, contra ~5 ms do salto
gRPC. Vale mostrar isso na apresentação: o gRPC não é o gargalo.

## Rodando localmente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r client/requirements.txt
bash generate_stubs.sh
cp .env.example .env      # e preencha a GEMINI_API_KEY
```

Em um terminal:

```bash
python server/server.py
```

Em outro:

```bash
python client/client.py --server localhost:50051
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

Dentro do REPL: `:help`, `:cards`, `:bytes` (liga a exibição do protobuf
serializado), `:quit`.

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
