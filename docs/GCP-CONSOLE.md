# Subindo o sistema pelo Google Cloud Console

Passo a passo pelo console, sem `gcloud` na sua máquina. Quem prefere linha de
comando tem `infra/setup_gcp.sh` e `infra/deploy.sh`, que fazem o mesmo.

O alvo é esta topologia:

```
   navegador                    vm-client                         vm-server
  (sua máquina)          nginx  :80  (pública)              Gateway :8000 (VPC)
        │  HTTP                 │                                  │
        └──────────────────────►│  /        -> React (build)        │
                                │  /api/*   -> ────────────────────►│  valida, JWT,
                                                                    │  JSON -> protobuf
                                                                    │     │        │
                                                          gRPC 127.0.0.1  │        │
                                                              Cartões :50052  Gastos :50051
                                                                    │        │
                                                                    └────┬───┘
                                                                         ▼
                                                              Cloud SQL PostgreSQL
                                                                (só IP privado)
```

Uma porta aberta para a internet no sistema inteiro: a 80 da vm-client. O
Gateway só atende de dentro da VPC, os microsserviços só de dentro da própria
vm-server, e o banco não tem endereço público.

---

## 1. Projeto e APIs

1. **Console → seletor de projeto → Novo projeto.** Anote o **ID do projeto**
   (não o nome: é o ID que aparece nos comandos).
2. **APIs e serviços → Biblioteca**, ative:
   - **Compute Engine API**
   - **Cloud SQL Admin API**
   - **Service Networking API** (o IP privado do Cloud SQL depende dela)
3. **Faturamento** precisa estar vinculado ao projeto. Sem isso o Compute
   Engine não cria VM.

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

**SQL → Criar instância → PostgreSQL**

| Campo | Valor |
|---|---|
| ID da instância | `banco-aula-sd` |
| Senha do usuário `postgres` | guarde-a |
| Versão | PostgreSQL 15 ou 16 |
| Predefinição | **Sandbox** (o mais barato; dá conta com folga) |
| Região | a mesma das VMs — `southamerica-east1` (São Paulo) |
| **Conexões** | marque **IP particular**, rede `default`; **desmarque IP público** |

Depois que a instância subir:

1. **Bancos de dados → Criar banco de dados:** `expenses`
2. **Usuários → Adicionar conta de usuário:** `expenses_app`, com senha própria
3. **Visão geral → Conectar-se a esta instância:** anote o **IP particular**
   (algo como `10.115.48.3`)

O esquema das tabelas é criado pelos próprios microsserviços ao iniciarem. Se
o usuário do banco não tiver permissão de DDL, rode `infra/cloud-sql.sql` pelo
**Cloud SQL Studio** antes.

## 4. Regras de firewall

**Rede VPC → Firewall → Criar regra de firewall.** Duas regras:

**`allow-gateway-internal`** — o Gateway, só de dentro da VPC

| Campo | Valor |
|---|---|
| Destinos | Tags de destino especificadas → `grpc-server` |
| Filtro de origem | Intervalos IPv4 → `10.128.0.0/9` |
| Protocolos e portas | TCP → `8000` |

**`allow-web-external`** — a interface web, para o navegador da apresentação

| Campo | Valor |
|---|---|
| Destinos | Tags de destino especificadas → `grpc-client` |
| Filtro de origem | Intervalos IPv4 → `0.0.0.0/0` |
| Protocolos e portas | TCP → `80` |

> `10.128.0.0/9` cobre as sub-redes automáticas da VPC `default` em todas as
> regiões. A regra do Gateway existe para dizer "só de dentro"; o que garante
> que o cliente não fale direto com o gRPC é o `--host 127.0.0.1` dos
> microsserviços, não o firewall — a regra `default-allow-internal` do GCP
> libera todas as portas entre VMs da mesma VPC.

## 5. vm-server (Gateway + microsserviços)

**Compute Engine → Instâncias de VM → Criar instância**

| Campo | Valor |
|---|---|
| Nome | `vm-server` |
| Região / zona | `southamerica-east1` / `southamerica-east1-a` |
| Tipo de máquina | `e2-small` |
| Disco de inicialização | Debian 12 |
| Rede → Tags de rede | `grpc-server` |
| Rede → Endereço IPv4 externo | **Nenhum** (ela não precisa sair para a internet) |

Em **Gerenciamento → Automação → Script de inicialização**, cole o conteúdo de
[`infra/startup-server.sh`](../infra/startup-server.sh) **depois de preencher o
bloco de CONFIGURAÇÃO no topo dele**: IP privado do Cloud SQL, senha do banco,
`JWT_SECRET`, o login do Gateway e, se for usar, a chave da Anthropic.

> Se você deixar `ANTHROPIC_API_KEY` em branco, tudo funciona: a interpretação
> em linguagem natural cai no interpretador por regras, que cobre os comandos
> do roteiro de demonstração.

Depois que a VM subir, anote o **IP interno** dela (ex.: `10.128.0.2`) e
confira pelo **SSH no navegador**:

```bash
sudo systemctl is-active cards expenses gateway   # três "active"
curl -s localhost:8000/health                     # {"status":"ok"}
sudo journalctl -u gateway -u cards -u expenses -f
```

Se algum serviço não subir, o motivo está no `journalctl`. O mais comum é a
senha do banco errada ou o IP privado trocado.

## 6. vm-client (interface web)

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

## 7. Conferindo ponta a ponta

Na interface:

1. **Cartões** → cadastre `Nubank` no crédito. O toast diz **201 Created**.
   Cadastre de novo: **200 OK**, porque já existia.
2. **Gastos → Novo gasto** → registre um lançamento.
3. **Laboratório → Rodar todos** → os doze cenários devem fechar em verde:
   três de 401, seis de 400 e três do caminho feliz. O de cadastrar cartão
   aceita 201 e 200 de propósito — 201 na primeira vez, 200 quando o cartão já
   existe, que é exatamente a diferença que a rota faz.
4. No **Cloud SQL Studio** (SQL → sua instância → Cloud SQL Studio), rode:

```sql
SELECT id, product, amount, card, category, date FROM expenses ORDER BY id DESC;
SELECT * FROM cards;
```

As linhas que você acabou de criar pela tela estão ali. É a prova de
persistência real que o enunciado pede.

## 8. Atualizando depois de mexer no código

Pelo SSH da VM correspondente:

```bash
# vm-server
cd /opt/sd-gastos-grpc && sudo git pull
sudo .venv/bin/pip install -q -r server/requirements.txt -r gateway/requirements.txt
sudo PATH=/opt/sd-gastos-grpc/.venv/bin:$PATH bash generate_stubs.sh
sudo systemctl restart cards expenses gateway

# vm-client
cd /opt/sd-gastos-grpc && sudo git pull
cd web && npm ci && npm run build && sudo systemctl reload nginx
```

## 9. Depois da apresentação

Para não queimar crédito: **Compute Engine → Instâncias de VM → Parar** as
duas, e **SQL → Parar** a instância do banco. Parar preserva os dados; excluir,
não.

---

## Se algo der errado no dia

| Sintoma | Onde olhar |
|---|---|
| A página não abre | A vm-client tem IP externo? A regra `allow-web-external` existe e a VM tem a tag `grpc-client`? |
| A página abre mas o login dá "Gateway não respondeu" | `GATEWAY_HOST` no nginx aponta para o IP **interno** certo? Na vm-client: `curl http://<ip-interno>:8000/health` |
| Login devolve 401 com a senha certa | `GATEWAY_USER`/`GATEWAY_PASSWORD` no `server.env` da vm-server. `sudo systemctl restart gateway` depois de mudar |
| Tudo 500 ou 503 | `sudo journalctl -u gateway -u cards -u expenses -n 100` — quase sempre é conexão com o banco |
| Sem IP externo na vm-client | Túnel SSH: `gcloud compute ssh vm-client --zone=... -- -L 8080:localhost:80` e abra `http://localhost:8080` |
| Nada da nuvem funciona | Plano B: `docker compose up --build` na sua máquina e abra `http://localhost:8080` — mesma arquitetura, PostgreSQL de verdade |
