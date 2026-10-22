# Roteiro da apresentação — 10 minutos

O limite é rígido: passar de 10 minutos zera o quesito de apresentação oral.
O roteiro abaixo fecha em **8 minutos**, deixando dois de folga para uma
pergunta ou para um erro de digitação.

**Antes de começar**, com o sistema já no ar e testado:

- [ ] `http://<IP-da-vm-client>` aberto e logado numa aba
- [ ] Um SSH na `vm-db` aberto, com a consulta digitada e **não executada**:
      `sudo docker exec postgres psql -U expenses_app -d expenses -c "SELECT id, product, amount, card, date FROM expenses ORDER BY id DESC"`
- [ ] **Três** abas de SSH abertas, uma por VM de backend, cada uma rodando o
      log do seu serviço: `journalctl -u gateway -f` na vm-server,
      `-u expenses -f` na vm-expenses, `-u cards -f` na vm-cards
- [ ] Alguns gastos já cadastrados, para o painel não aparecer vazio
- [ ] Um cartão que **não** existe em mente (ex.: "Bradesco"), para o caso de erro

---

## 0:00 — 1:30 · O que é e por onde passa

Mostre a **tela de login** — o painel da esquerda já desenha os quatro saltos.

> "Controle de gastos pessoais. São quatro serviços, **cada um na sua própria
> VM no GCP**: o frontend que vocês estão vendo, um API Gateway em FastAPI, e
> dois microsserviços gRPC — um dono dos cartões, outro dos gastos — falando
> com um PostgreSQL que roda numa quinta VM.
>
> O frontend só conhece o Gateway. Os microsserviços só aceitam conexão do
> Gateway e um do outro, por um par de regras de firewall. A única porta do
> sistema aberta para a internet é a 80 desta máquina aqui."

Faça o login. **Não explique JWT ainda** — o Diagnóstico faz isso melhor,
mostrando o 401.

## 1:30 — 3:00 · O caminho feliz, até o banco

**Painel:** aponte os quatro cartões de número e um dos gráficos.

> "Cada gráfico aqui é um `SummaryByGroup`, que é um RPC do microsserviço de
> Gastos. O Gateway recebeu o GET, traduziu para protobuf e devolveu JSON."

**Gastos → Novo gasto.** Preencha e salve. O toast confirma.

Vá para o SSH da **vm-db** e rode a consulta.

> "Está no banco. Não é lista em memória, não é mock: é uma linha nova no
> PostgreSQL, que o microsserviço de Gastos gravou depois de perguntar ao de
> Cartões, por gRPC, se aquele cartão existia."

Agora o momento mais forte da demonstração: aponte as **três abas de SSH**.

> "Esta é a mesma requisição, nas três máquinas. O Gateway gerou este
> identificador quando recebeu o POST, mandou junto na chamada gRPC para o
> serviço de Gastos, e o de Gastos repassou para o de Cartões. Três VMs, três
> logs, o mesmo id."

```
vm-server    [45b51b84] RegisterExpense  JSON -> protobuf 40 bytes
vm-expenses  [45b51b84] RegisterExpense  from 10.128.0.2  teclado 389.90 Nubank/credit
vm-cards     [45b51b84] ValidateCard     from 10.128.0.5  Nubank / credit
```

Se perguntarem de onde vem o id, ele também volta no cabeçalho
`X-Request-Id` da resposta — dá para abrir na aba Diagnóstico, no painel da
direita, que registra toda requisição feita no sistema.

## 3:00 — 4:00 · Alteração e remoção

De volta em **Gastos**, edite o lançamento (o lápis), mude o valor, salve.
Remova outro (a lixeira), confirme.

Volte ao SSH da **vm-db** e rode a consulta de novo.

> "Consulta, inserção, alteração e remoção — as quatro batem no banco. O
> `UpdateExpense` revalida o cartão no CardService, igual ao registro: editar
> pode trocar o cartão tanto quanto criar pode inventar um."

## 4:00 — 6:00 · Diagnóstico: 401, 400, 201

**Diagnóstico → Verificar tudo.** Em poucos segundos as doze verificações
fecham.

> "Cada linha dessas é uma requisição HTTP de verdade. A coluna da direita
> mostra o que era esperado e o que o Gateway devolveu."

Abra **uma** troca de 401 no painel da direita:

> "Requisição sem o cabeçalho `Authorization`. O Gateway devolve 401 na borda,
> antes de abrir qualquer canal gRPC — nenhum microsserviço chegou a ser
> chamado."

Abra **uma** de 400 — a de campos ausentes:

> "Corpo vazio. Os modelos Pydantic do Gateway recusam, e a resposta diz qual
> campo faltou."

E a de **cartão inexistente**, que é a mais interessante:

> "Esta também é 400, mas por outro motivo: o payload estava perfeito. Quem
> recusou foi o microsserviço de Cartões, consultado por gRPC pelo de Gastos.
> Validação de formato na borda, validação de negócio no dono do dado."

Termine com uma de **201**.

## 6:00 — 7:30 · Linguagem natural

**Assistente.** Digite:

```
gastei 89 reais num teclado mecânico no crédito do Nubank
```

> "O Gateway interpretou a frase e despachou pelos mesmos RPCs do formulário.
> O microsserviço não sabe que existe um modelo de linguagem: chegou o mesmo
> protobuf que chegaria se eu tivesse preenchido o formulário."

Agora o comando com um cartão que não existe:

```
gastei 30 reais de uber no crédito do cartão Bradesco
```

> "O modelo obedeceu e mandou 'Bradesco'. O sistema não gravou: o CardService
> disse que não conhece esse cartão, e a interface, em vez de só recusar,
> oferece as saídas."

Clique em **cadastrar Bradesco (Crédito) e lançar**.

> "Duas chamadas: `RegisterCard` e depois `RegisterExpense`. Nada foi gravado
> às cegas."

## 7:30 — 8:00 · Fechamento

> "Resumindo a arquitetura: o frontend fala só HTTP/JSON com o Gateway; o
> Gateway autentica, valida e traduz para gRPC; cada microsserviço é dono de
> uma tabela e só chega na do outro pelo contrato `.proto`; e o banco só
> aceita conexão dos dois microsserviços. Obrigado."

---

## Perguntas prováveis, e a resposta curta

**"Por que não tem chave estrangeira entre `expenses` e `cards`?"**
Ela acoplaria os dois serviços por baixo do contrato: o banco garantiria algo
que o gRPC deveria garantir. A checagem é o `ValidateCard`, e é por isso que
ela continua valendo mesmo se um dia as tabelas ficarem em bancos diferentes.

**"O que acontece se o serviço de Cartões cair?"**
O de Gastos recusa o registro com `UNAVAILABLE` em vez de gravar sem conferir.
Tem teste para isso em `server/test_services.py` (`check_cards_down`).

**"Por que FastAPI e não Spring Boot?"**
O enunciado aceita "framework equivalente". O resto do sistema é Python, e o
`.proto` é compartilhado entre Gateway e microsserviços — um Gateway em Java
duplicaria a geração de stubs sem ganho nenhum.

**"O frontend não poderia falar gRPC direto?"**
Navegador não fala gRPC sem um proxy (gRPC-Web). E o enunciado pede o contrário:
ponto único de entrada, com autenticação e validação na borda.

**"Onde está a comunicação entre microsserviços?"**
`server/expenses_service.py`, método `_validate_card`: o serviço de Gastos abre
um canal gRPC para o de Cartões antes de gravar ou de alterar — e, na nuvem,
isso atravessa a rede entre duas VMs. O log das duas mostra o mesmo id.

**"Vocês usam deadline nas chamadas gRPC?"**
Sim, em todas. Elas passam pela mesma função `call()` no Gateway, que fixa 10
segundos; a chamada entre microsserviços usa 5. Sem prazo, um serviço lento
prenderia o Gateway junto com ele.

**"E retry?"**
Não fazemos retry de chamada gRPC. `RegisterExpense` não é idempotente — um
reenvio criaria um gasto duplicado, porque não temos `request_id` de
operação. Para habilitar retry com segurança, o caminho seria uma chave de
idempotência no `RegisterExpenseRequest`.

**"Como vocês evoluem o contrato?"**
Só adicionando. `UpdateExpense` e `DeleteExpense` entraram como mensagens
novas, com numeração própria; nenhum número existente foi reaproveitado ou
reutilizado. Os stubs não são versionados — `generate_stubs.sh` os recria —,
então não existe stub dessincronizado do `.proto`.

**"E se a API da Anthropic estiver fora do ar?"**
O Gateway cai num interpretador por regras (`language/nlu.py`,
`interpret_offline`) e a resposta diz qual dos dois respondeu. Nada da
demonstração depende da LLM — e, sem chave configurada, é esse o caminho que
roda o tempo todo.
