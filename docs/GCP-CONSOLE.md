# Subindo pelo console, clicando

Este é o caminho manual. **O recomendado é o script**, documentado em
[`DEPLOY.md`](DEPLOY.md) — um comando, de 10 a 15 minutos, e a interface sobe
com dados.

Use este documento se preferir clicar, se quiser entender o que o script faz,
ou se algum passo dele falhar e você precisar completá-lo à mão.

> Uma diferença: este guia descreve o banco como **Cloud SQL**, que era a
> versão anterior. O script usa **PostgreSQL em container na `vm-db`**, que é
> a topologia atual. As seções de firewall e de VMs valem para as duas; a de
> banco, não.

---

O alvo é esta topologia — **cada serviço na sua própria VM**:

```
   navegador                vm-client                      vm-server
  (sua máquina)        nginx :80 (pública)            API Gateway :8000
        │  HTTP                 │                             │
        └──────────────────────►│  /      -> React (build)    │
                                │  /api/* ────────────────────►  JWT · valida
                                                              │  JSON -> protobuf
                                                    ┌─────────┴─────────┐
                                               gRPC │                   │ gRPC
                                                    ▼                   ▼
                                              vm-cards             vm-expenses
                                          Cartões :50052  ◄──gRPC── Gastos :50051
                                                    │   ValidateCard    │
                                                    └─────────┬─────────┘
                                                              ▼
                                                   Cloud SQL PostgreSQL
                                                     (só IP privado)
```

| VM | Tag de rede | IP externo | O que roda |
|---|---|---|---|
| `vm-client` | `grpc-client` | **sim** | nginx :80 — frontend e proxy de `/api` |
| `vm-server` | `grpc-server` | não | API Gateway :8000 |
| `vm-cards` | `grpc-service` | não | microsserviço de Cartões :50052 |
| `vm-expenses` | `grpc-service` | não | microsserviço de Gastos :50051 |

Uma porta aberta para a internet no sistema inteiro: a 80 da `vm-client`. O
Gateway só atende de dentro da VPC, os microsserviços só atendem ao Gateway e
um ao outro, e o banco não tem endereço público.

**A ordem de criação importa.** Cada VM precisa do IP interno da anterior:
Cartões não depende de ninguém, Gastos precisa de Cartões, o Gateway precisa
dos dois, e a vm-client precisa do Gateway.

---

## 1. Projeto e APIs

1. **Console → seletor de projeto → Novo projeto.** Anote o **ID do projeto**
   (não o nome: é o ID que aparece nos comandos).
2. **APIs e serviços → Biblioteca**, ative:
   - **Compute Engine API**
   - **Cloud SQL Admin API**
   - **Service Networking API** (o IP privado do Cloud SQL depende dela)
3. **Faturamento precisa estar ATIVO no projeto**, não só vinculado. São
   coisas diferentes: o projeto pode ter uma conta de faturamento associada e
   ainda assim estar com a cobrança desativada — foi o caso do `SD 2026`.
   Confira em **Faturamento** no menu lateral; se disser que o faturamento
   está desativado, reative. Enquanto não estiver ativo, toda chamada ao
   Compute Engine falha com *"This API method requires billing to be
   enabled"*, e nenhuma VM é criada.

   Para conferir pelo terminal:

   ```bash
   gcloud billing projects describe <PROJECT_ID>   # billingEnabled: true
   ```

## 2. Rede privada para o banco

O Cloud SQL sem IP público conversa com as VMs por um *peering* de acesso
privado a serviços. Configure uma vez:

1. **Rede VPC → Rede VPC → default → Acesso a serviços particulares →
   Conexões particulares com serviços → Alocar intervalo de IP**
   - Nome: `google-managed-services-default`
   - Intervalo: **Automático**, prefixo `/16`
2. Ainda nessa tela, **Criar conexão** usando o intervalo alocado.

> Pulando este passo, a única saída é dar IP público ao banco — o que expõe o
> Postgres à internet. Não faça isso.

## 3. Cloud SQL (PostgreSQL)

### Se o projeto já tem a instância do Trabalho 1

É o caso do projeto `SD 2026`, que já tem a `banco-aula-sd`. Então não crie
outra — só faltam três ajustes:

1. **SQL → banco-aula-sd → Iniciar.** Ela fica parada entre as aulas
   (`activationPolicy: NEVER`), e parada não aceita conexão. Ligar leva uns
   dois minutos.
2. **Editar → Conexões → marque IP particular**, rede `default`. O console
   oferece alocar o intervalo e criar o peering ali mesmo; aceite. Isto é
   obrigatório: as VMs dos microsserviços **não têm IP externo**, então só
   alcançam o banco pela rede privada. Pode deixar o IP público ligado — ele
   não atrapalha, e o Cloud SQL Studio continua funcionando.
3. **Anote o IP particular** que aparece em *Visão geral → Conectar-se a esta
   instância*. É ele que vai no `PGHOST` dos dois scripts.

> O IP público com *redes autorizadas* — como está hoje, liberando o
> `34.31.110.75` da antiga `vm-aula` — não serve mais: aquela VM não existe, e
> as novas não terão endereço público para autorizar. Daí o IP particular.

Confira ainda que existem o banco `expenses` e o usuário `expenses_app`
(abas **Bancos de dados** e **Usuários**). Se o usuário não existir, crie e
guarde a senha.

### Se estiver criando do zero

**SQL → Criar instância → PostgreSQL**

| Campo | Valor |
|---|---|
| ID da instância | `banco-aula-sd` |
| Senha do usuário `postgres` | guarde-a |
| Versão | PostgreSQL 15 ou mais novo |
| Predefinição | **Sandbox** (a mais barata; sobra para este volume) |
| Região | a mesma das VMs |
| **Conexões** | marque **IP particular**, rede `default` |

Depois que subir: crie o banco `expenses`, o usuário `expenses_app`, e anote
o **IP particular**.

As tabelas são criadas pelos próprios microsserviços ao iniciarem. Se o
usuário do banco não tiver permissão de DDL, rode `infra/cloud-sql.sql` pelo
**Cloud SQL Studio** antes.

> **Atenção ao custo.** A `banco-aula-sd` está num tier `db-custom-2-8192`
> (2 vCPU, 8 GB) — bem acima do necessário e caro para ficar ligado. Depois da
> apresentação, **pare a instância**.

## 4. Regras de firewall

**Rede VPC → Firewall → Criar regra de firewall.** Quatro regras. As duas
primeiras já existiam; as duas últimas são o que substitui o `127.0.0.1` agora
que os microsserviços têm VMs próprias.

| Nome | Prioridade | Ação | Destinos (tag) | Origem | Portas |
|---|---|---|---|---|---|
| `allow-web-external` | 1000 | Permitir | `grpc-client` | `0.0.0.0/0` | `tcp:80` |
| `allow-gateway-internal` | 1000 | Permitir | `grpc-server` | `10.128.0.0/9` | `tcp:8000` |
| `allow-grpc-internal` | **800** | Permitir | `grpc-service` | **tags** `grpc-server`, `grpc-service` | `tcp:50051,50052` |
| `deny-grpc-external` | **900** | **Negar** | `grpc-service` | `0.0.0.0/0` | `tcp:50051,50052` |

> No formulário, "Origem" tem duas abas: **Intervalos IPv4** e **Tags de
> origem**. As duas últimas regras usam *tags de origem*, não intervalo — é o
> que amarra o acesso às VMs certas em vez de a uma faixa de IP.

**Por que a prioridade importa.** No GCP, número menor é avaliado primeiro. O
par 800/900 significa: o Gateway e os microsserviços entram, todo o resto é
negado. Sem o `deny`, a regra `default-allow-internal` — que o GCP cria
sozinho em toda VPC com prioridade 65534 e libera **todas** as portas entre
VMs — deixaria a `vm-client` alcançar os microsserviços direto, e o requisito
de o frontend falar só com o Gateway cairia por terra.

Enquanto os três processos dividiam a `vm-server`, quem garantia isso era o
`127.0.0.1`. Com as VMs separadas, quem garante é este par de regras.

## 5. vm-cards e vm-expenses (os microsserviços)

**Compute Engine → Instâncias de VM → Criar instância**, duas vezes. As duas
são iguais menos pelo nome e pelo script:

| Campo | Valor |
|---|---|
| Nome | `vm-cards`, depois `vm-expenses` |
| Região / zona | `southamerica-east1` / `southamerica-east1-a` |
| Tipo de máquina | `e2-small` |
| Disco de inicialização | Debian 12 |
| Rede → Tags de rede | `grpc-service` |
| Rede → Endereço IPv4 externo | **Nenhum** |

**Primeiro a `vm-cards`.** Em *Gerenciamento → Automação → Script de
inicialização*, cole [`infra/startup-cards.sh`](../infra/startup-cards.sh)
com o bloco de configuração preenchido (IP privado do Cloud SQL e senha do
banco). Quando subir, **anote o IP interno** — as outras duas VMs precisam
dele.

```bash
sudo systemctl is-active cards     # active
sudo journalctl -u cards -f
```

**Depois a `vm-expenses`**, com [`infra/startup-expenses.sh`](../infra/startup-expenses.sh).
Aqui o `CARDS_ADDR` recebe o IP interno da `vm-cards` com a porta — por
exemplo `10.128.0.4:50052`. Sem isso nenhum gasto é gravado: o serviço recusa
em vez de gravar sem conferir o cartão. Anote o IP interno desta também.

> Confira que uma alcança a outra, pelo SSH da `vm-expenses`:
> `nc -vz <ip-da-vm-cards> 50052`

## 6. vm-server (o API Gateway)

**Criar instância** de novo:

| Campo | Valor |
|---|---|
| Nome | `vm-server` |
| Zona | a mesma das outras |
| Tipo de máquina | `e2-small` |
| Disco de inicialização | Debian 12 |
| Rede → Tags de rede | `grpc-server` |
| Rede → Endereço IPv4 externo | **Nenhum** |

Cole [`infra/startup-server.sh`](../infra/startup-server.sh) com o
`CARDS_ADDR` e o `EXPENSES_ADDR` apontando para os IPs internos que você
anotou, mais o `JWT_SECRET`, o login do Gateway e, se for usar, a chave da
Anthropic.

> Esta VM **não** recebe as credenciais do banco. Quem toca o PostgreSQL são
> os microsserviços; o Gateway só fala gRPC com eles.

> Se você deixar `ANTHROPIC_API_KEY` em branco, tudo funciona: a interpretação
> em linguagem natural cai no interpretador por regras, que cobre os comandos
> do roteiro de demonstração.

Anote o **IP interno** e confira pelo SSH do navegador:

```bash
sudo systemctl is-active gateway   # active
curl -s localhost:8000/health      # {"status":"ok"}
sudo journalctl -u gateway -f
```

Se o Gateway subir mas toda chamada der 503, ele não está alcançando os
microsserviços: confira os endereços no `server.env` e a regra
`allow-grpc-internal`.

## 7. vm-client (interface web)

**Criar instância** de novo:

| Campo | Valor |
|---|---|
| Nome | `vm-client` |
| Zona | a mesma da vm-server |
| Tipo de máquina | `e2-small` |
| Disco de inicialização | Debian 12 |
| Rede → Tags de rede | `grpc-client` |
| Rede → Endereço IPv4 externo | **Efêmero** (é por ele que o navegador entra) |

Em **Gerenciamento → Automação → Script de inicialização**, cole
[`infra/startup-client.sh`](../infra/startup-client.sh) com o `GATEWAY_HOST`
preenchido com o **IP interno da vm-server**.

O script instala o nginx e o Node 20, compila o frontend e publica tudo na
porta 80. O primeiro build leva alguns minutos; acompanhe pelo SSH:

```bash
sudo journalctl -u google-startup-scripts -f
```

Quando terminar, abra `http://<IP-EXTERNO-DA-VM-CLIENT>` no navegador e entre
com o `GATEWAY_USER` e a `GATEWAY_PASSWORD` que você definiu no passo 5.

## 8. Conferindo ponta a ponta

Na interface:

1. **Cartões** → cadastre `Nubank` no crédito. O toast diz que foi criado.
   Cadastre de novo: ele avisa que já existia, porque não houve criação.
2. **Gastos → Novo gasto** → registre um lançamento.
3. **Diagnóstico → Verificar tudo** → as doze verificações devem fechar em
   verde: três de acesso, seis de validação e três de operação.
4. No **Cloud SQL Studio** (SQL → sua instância → Cloud SQL Studio), rode:

```sql
SELECT id, product, amount, card, category, date FROM expenses ORDER BY id DESC;
SELECT * FROM cards;
```

As linhas que você acabou de criar pela tela estão ali. É a prova de
persistência real que o enunciado pede.

### A requisição atravessando as três VMs

Abra três abas de SSH, uma por VM, e deixe rodando:

```bash
# vm-server
sudo journalctl -u gateway -f
# vm-expenses
sudo journalctl -u expenses -f
# vm-cards
sudo journalctl -u cards -f
```

Agora registre um gasto pela tela. O mesmo identificador aparece nas três:

```
vm-server    [45b51b84] RegisterExpense  JSON -> protobuf 40 bytes
vm-expenses  [45b51b84] RegisterExpense  from 10.128.0.2:58568  teclado 389.90 Nubank/credit
vm-cards     [45b51b84] ValidateCard     from 10.128.0.5:54026  Nubank / credit
```

O Gateway gera esse id a cada requisição HTTP e o envia na metadata de cada
chamada gRPC; o serviço de Gastos o repassa ao de Cartões. É o que permite
seguir uma operação pelo sistema inteiro mesmo com várias pessoas usando ao
mesmo tempo — e, na apresentação, é a demonstração mais direta de que as três
máquinas estão de fato conversando.

O id também volta ao navegador, no cabeçalho `X-Request-Id` da resposta.

## 9. Atualizando depois de mexer no código

Pelo SSH da VM correspondente:

```bash
# vm-cards e vm-expenses
cd /opt/sd-gastos-grpc && sudo git pull
sudo .venv/bin/pip install -q -r server/requirements.txt
sudo PATH=/opt/sd-gastos-grpc/.venv/bin:$PATH bash generate_stubs.sh
sudo systemctl restart cards        # ou: expenses

# vm-server
cd /opt/sd-gastos-grpc && sudo git pull
sudo .venv/bin/pip install -q -r server/requirements.txt -r gateway/requirements.txt
sudo PATH=/opt/sd-gastos-grpc/.venv/bin:$PATH bash generate_stubs.sh
sudo systemctl restart gateway

# vm-client
cd /opt/sd-gastos-grpc && sudo git pull
cd web && npm ci && npm run build && sudo systemctl reload nginx
```

> Mexeu no `.proto`? Então **as três** VMs de backend precisam do
> `generate_stubs.sh` e do restart. Stub velho de um lado e novo do outro é o
> erro mais chato de diagnosticar, porque o sintoma é um campo chegando vazio
> sem nenhum erro.

## 10. Depois da apresentação

Para não queimar crédito: **Compute Engine → Instâncias de VM → Parar** as
quatro, e **SQL → Parar** a instância do banco. Parar preserva os dados;
excluir, não.

---

## Se algo der errado no dia

| Sintoma | Onde olhar |
|---|---|
| A página não abre | A `vm-client` tem IP externo? A regra `allow-web-external` existe e a VM tem a tag `grpc-client`? |
| A página abre, mas o login diz que não conectou | O `GATEWAY_HOST` do nginx aponta para o IP **interno** da `vm-server`? Na `vm-client`: `curl http://<ip>:8000/health` |
| Login devolve 401 com a senha certa | `GATEWAY_USER`/`GATEWAY_PASSWORD` no `server.env` da `vm-server`; `sudo systemctl restart gateway` depois de mudar |
| **Tudo devolve 503** | O Gateway não alcança os microsserviços. Confira `CARDS_ADDR` e `EXPENSES_ADDR` no `server.env`, e a regra `allow-grpc-internal`. Da `vm-server`: `nc -vz <ip-vm-cards> 50052` |
| Gasto recusado dizendo que o serviço de Cartões não respondeu | A `vm-expenses` não alcança a `vm-cards`. O `CARDS_ADDR` dela está certo? A tag `grpc-service` está nas duas? |
| Um serviço não sobe | `sudo journalctl -u <serviço> -n 100` — quase sempre é senha do banco errada ou IP privado trocado |
| Os logs não mostram o mesmo id | Normal se você mexeu só numa VM: as três precisam estar com o mesmo commit |
| Sem IP externo na `vm-client` | Túnel: `gcloud compute ssh vm-client --zone=... -- -L 8080:localhost:80`, e abra `http://localhost:8080` |
| **Nada da nuvem funciona** | Plano B: `docker compose up --build` na sua máquina e abra `http://localhost:8080`. Mesma arquitetura, cada serviço no seu host, PostgreSQL de verdade |

> **A ordem de subida, se precisar reiniciar tudo:** `vm-cards`,
> `vm-expenses`, `vm-server`, `vm-client`. O Gateway tolera os
> microsserviços subirem depois dele — o canal gRPC reconecta sozinho —, mas
> começar pela ordem certa poupa um minuto de 503 na tela.
