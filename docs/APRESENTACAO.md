# Roteiro da apresentação — 10 minutos

O limite é rígido: passar de 10 minutos zera o quesito de apresentação oral.
O roteiro abaixo fecha em **8 minutos**, deixando dois de folga para uma
pergunta ou para um erro de digitação.

**Antes de começar**, com o sistema já no ar e testado:

- [ ] `http://<IP-da-vm-client>` aberto e logado numa aba
- [ ] Cloud SQL Studio aberto em outra aba, com a consulta já digitada:
      `SELECT id, product, amount, card, category, date FROM expenses ORDER BY id DESC;`
- [ ] SSH da vm-server aberto numa terceira, rodando
      `sudo journalctl -u gateway -u cards -u expenses -f`
- [ ] Alguns gastos já cadastrados, para o painel não aparecer vazio
- [ ] Um cartão que **não** existe em mente (ex.: "Bradesco"), para o caso de erro

---

## 0:00 — 1:30 · O que é e por onde passa

Mostre a **tela de login** — o painel da esquerda já desenha os quatro saltos.

> "Controle de gastos pessoais. São quatro processos separados: o frontend que
> vocês estão vendo, um API Gateway em FastAPI, e dois microsserviços gRPC — um
> dono dos cartões, outro dos gastos — falando com um PostgreSQL no Cloud SQL.
>
> O frontend só conhece o Gateway. Os microsserviços escutam em 127.0.0.1: nem
> com a regra de firewall aberta alguém de fora da VM chega neles. A única
> porta do sistema aberta para a internet é a 80 desta máquina aqui."

Faça o login. **Não explique JWT ainda** — o Laboratório faz isso melhor,
mostrando o 401.

## 1:30 — 3:00 · O caminho feliz, até o banco

**Painel:** aponte os quatro cartões de número e um dos gráficos.

> "Cada gráfico aqui é um `SummaryByGroup`, que é um RPC do microsserviço de
> Gastos. O Gateway recebeu o GET, traduziu para protobuf e devolveu JSON."

**Gastos → Novo gasto.** Preencha e salve. O toast confirma.

Vá para a aba do **Cloud SQL Studio** e rode a consulta.

> "Está no banco. Não é lista em memória, não é mock: é uma linha nova no
> PostgreSQL, que o microsserviço de Gastos gravou depois de perguntar ao de
> Cartões, por gRPC, se aquele cartão existia."

Se der tempo, mostre o `journalctl`: as linhas `RegisterExpense JSON ->
protobuf N bytes`, `RegisterExpense from ipv6:...`, `ValidateCard from ...`.
São três linhas que provam os três saltos.

## 3:00 — 4:00 · Alteração e remoção

De volta em **Gastos**, edite o lançamento (o lápis), mude o valor, salve.
Remova outro (a lixeira), confirme.

Volte ao **Cloud SQL Studio** e rode a consulta de novo.

> "Consulta, inserção, alteração e remoção — as quatro batem no banco. O
> `UpdateExpense` revalida o cartão no CardService, igual ao registro: editar
> pode trocar o cartão tanto quanto criar pode inventar um."

## 4:00 — 6:00 · Laboratório: 401, 400, 201

**Laboratório → Rodar todos.** Em poucos segundos os doze cenários fecham.

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

> "O Gateway mandou a frase para a Claude, recebeu este JSON — mostre o bloco
> escuro — e despachou pelos mesmos RPCs do formulário. O microsserviço não
> sabe que existe um modelo de linguagem: chegou o mesmo protobuf."

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
> uma tabela e só chega na do outro pelo contrato `.proto`; e o banco é um
> Cloud SQL com IP privado. Obrigado."

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
um canal gRPC para o de Cartões antes de gravar ou de alterar.

**"E se a API da Anthropic estiver fora do ar?"**
O Gateway cai num interpretador por regras (`language/nlu.py`,
`interpret_offline`) e a resposta diz que caiu — a etiqueta amarela no card.
Nada da demonstração depende da LLM.
