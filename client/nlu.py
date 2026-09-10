#!/usr/bin/env python3
"""Microsserviço A — camada de linguagem natural.

Transforma o texto do usuário num comando estruturado. Nada aqui fala gRPC: a
saída é um dict {"action": ..., "args": {...}} que o client.py despacha.

Pede JSON no próprio prompt em vez de usar tool calling. Faz o mesmo trabalho
(o modelo escolhe a ação) com muito menos superfície de API para quebrar entre
versões do SDK.

O prompt é escrito em português, o mesmo idioma dos comandos que ele interpreta.
As chaves e os valores do JSON continuam em inglês porque são o contrato com o
código — trocá-los quebraria o despacho no client.py.
"""

import json
import os
import re
import sys
import time
import unicodedata

from period import PERIOD_LABELS

# Migrado do Gemini para a API da Anthropic: o free tier do Gemini dava apenas
# 20 requisições por dia por modelo, e as chamadas levavam de 10 a 25 segundos
# quando o serviço estava carregado — inviável numa demonstração ao vivo.
#
# Liste os modelos disponíveis na sua conta com:
#     python client/nlu.py --models
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_TIMEOUT = 30.0


def model_name():
    """O modelo em uso, lido a cada chamada — nunca na importação.

    O client.py carrega o .env dentro de main(), depois de já ter importado
    este módulo. Uma constante avaliada no import ignoraria o arquivo inteiro,
    e o cliente rodaria com o padrão do código sem ninguém perceber.
    """
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)


def _timeout():
    return float(os.environ.get("ANTHROPIC_TIMEOUT", DEFAULT_TIMEOUT))


# A resposta é um JSON curto (~100 tokens), mas o modelo raciocina antes de
# responder e esse raciocínio também conta aqui. A folga evita corte no meio.
MAX_TOKENS = 4096

CATEGORIES = (
    "food", "transport", "technology", "leisure",
    "health", "housing", "education", "clothing", "other",
)

_PROMPT = """Você converte comandos em português sobre gastos pessoais em JSON.
Hoje é {today}.

Responda SOMENTE com um objeto JSON, sem markdown e sem comentários, no formato:
{{"action": "<action>", "args": {{...}}}}

AÇÕES DISPONÍVEIS

1) "register_card" — cadastrar um ou mais cartões
   args: {{"cards": [{{"name": "Nubank", "method": "CREDIT"}}]}}

2) "list_cards" — mostrar os cartões já cadastrados
   args: {{}}

3) "register_expense" — anotar uma despesa
   args: {{"product": "teclado mecânico", "description": "", "amount": 89.0,
           "card": "Nubank", "method": "CREDIT", "category": "technology",
           "date_label": "today"}}
   Quando o gasto aconteceu vai SEMPRE em "date_label" — nunca em "period",
   que não existe nesta ação, e nunca vazio se o texto falar de tempo.
   Aceita "today", "yesterday", "day_before_yesterday" e também qualquer
   rótulo da lista "period" quando o texto for vago: "mês passado" vira
   "last_month", "semana passada" vira "this_week". Use "date": "AAAA-MM-DD"
   só quando o texto disser uma data explícita ("dia 3", "12/08").

4) "search_expenses" — listar despesas
   args: {{"card": "", "method": "", "category": "", "period": "this_month"}}

5) "summary" — totais agrupados
   args: {{"group_by": "category", "card": "", "method": "",
           "category": "", "period": "all_time"}}
   "group_by" só pode ser "category", "card" ou "method".

6) "unknown" — quando não der para entender o comando
   args: {{"reason": "uma frase curta explicando o motivo"}}

VALORES PERMITIDOS

method: "CREDIT", "DEBIT" ou "" (vazio = não mencionado)
period: {periods}
category: {categories}

CARTÕES CADASTRADOS
{cards}

REGRAS
- Use apenas cartões da lista acima. Se o usuário citar um que não está lá,
  copie o nome exatamente como ele escreveu — quem valida é o servidor.
- Nunca invente uma categoria fora da lista. Na dúvida, use "other".
- Não calcule datas. Devolva o rótulo do período; quem faz a conta é o programa.
- Em search_expenses e summary, só use um período se o texto falar de tempo.
  Sem menção a tempo, use "all_time" — "tudo", "todos" e "meus gastos" são
  "all_time", não "this_month".
- Campos que o texto não mencionar ficam com string vazia "".
- "no crédito"/"parcelei" => CREDIT. "no débito"/"na função débito" => DEBIT.

COMANDO DO USUÁRIO
{text}"""


def build_prompt(text, cards, today):
    if cards:
        lines = "\n".join(
            "- %s (%s)" % (name, ", ".join(methods)) for name, methods in cards)
    else:
        lines = "- (no cards registered yet)"
    return _PROMPT.format(
        today=today,
        periods=", ".join(PERIOD_LABELS),
        categories=", ".join(CATEGORIES),
        cards=lines,
        text=text,
    )


_anthropic_client = None


def _client():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY não está definida. Copie .env.example para "
                ".env e preencha, ou rode o cliente com --offline.")
        _anthropic_client = Anthropic(api_key=key, timeout=_timeout())
    return _anthropic_client


# Erros que valem uma nova tentativa: sobrecarga e limite de taxa. Uma chave
# inválida (401) ou um modelo inexistente (404) não melhoram com espera.
_RETRYABLE = ("429", "500", "502", "503", "529", "overloaded", "rate_limit",
              "Timeout", "Connection")


def _retryable(error):
    return any(mark in str(error) for mark in _RETRYABLE)


def explain(error):
    """Resume o erro numa linha — o nome da exceção sozinho não ajuda a agir."""
    text = str(error)
    if "credit balance" in text or "billing" in text.lower():
        return "sem créditos na conta — adicione em console.anthropic.com/settings/billing"
    if "authentication" in text.lower() or "401" in text or "invalid x-api-key" in text:
        return "chave de API inválida"
    if "429" in text or "rate_limit" in text:
        return "limite de requisições atingido; tente de novo em alguns segundos"
    if "529" in text or "overloaded" in text:
        return "API sobrecarregada (529)"
    if "404" in text or "not_found" in text:
        return "modelo %s indisponível para esta conta" % model_name()
    if "Timeout" in text or "timeout" in text.lower():
        return "tempo esgotado esperando a resposta"
    return "%s: %s" % (type(error).__name__, text[:90])


def _first_text(message):
    """O texto da resposta, ignorando blocos de raciocínio que vêm antes.

    Com o pensamento ligado, content[0] pode ser um bloco thinking — pegar o
    índice zero às cegas quebraria de forma intermitente.
    """
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def interpret(text, cards, today, model=None):
    """Texto -> {"action": ..., "args": {...}} usando a API da Anthropic.

    `cards` é [(name, [rótulos de método])], vindo do RPC ListCards.

    Só levanta o erro se todas as tentativas falharem — aí o client.py cai no
    interpretador offline.
    """
    prompt = build_prompt(text, cards, today)
    name = model or model_name()

    # A extração é simples e a lista de opções é fechada: esforço baixo entrega
    # o mesmo resultado gastando menos tokens e respondendo mais rápido. Haiku
    # não aceita o parâmetro, então ele só vai quando o modelo suporta.
    options = {}
    if not name.startswith("claude-haiku"):
        options["output_config"] = {"effort": "low"}

    last_error = None
    for delay in (0, 1.5, 4):
        if delay:
            time.sleep(delay)
        try:
            message = _client().messages.create(
                model=name,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                **options
            )
            # Uma recusa do classificador de segurança vem com HTTP 200 e sem
            # texto útil; sem esta checagem viraria um JSONDecodeError confuso.
            if getattr(message, "stop_reason", None) == "refusal":
                raise RuntimeError("o modelo recusou interpretar este comando")
            return _load_json(_first_text(message))
        except Exception as error:
            last_error = error
            if not _retryable(error):
                break

    raise last_error


def _load_json(raw):
    """Tolera cercas de markdown, que aparecem mesmo em modo JSON."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
    command = json.loads(text)
    command.setdefault("args", {})
    return command


# --------------------------------------------------------------------------
# Offline fallback
#
# Não é uma segunda implementação "por precaução": é o seguro contra o maior
# risco do projeto, que é a API da LLM estar fora do ar, sem créditos ou
# inalcançável pela rede no dia da apresentação. Cobre os comandos do roteiro
# de demonstração, não o português inteiro.
#
# As listas de palavras abaixo estão em português porque são dados linguísticos
# do idioma que o usuário fala, não identificadores de código.
# --------------------------------------------------------------------------

_AMOUNT = re.compile(r"(\d+(?:[.,]\d{1,2})?)")

_CATEGORY_KEYWORDS = {
    "food": ("almoco", "jantar", "lanche", "comida", "mercado", "padaria",
             "cafe", "pizza", "ifood", "restaurante", "hamburguer"),
    "transport": ("uber", "gasolina", "combustivel", "onibus", "metro", "taxi",
                  "estacionamento", "pedagio", "passagem"),
    "technology": ("teclado", "mouse", "monitor", "notebook", "celular", "fone",
                   "ssd", "cabo", "carregador", "computador", "iphone", "ipad",
                   "tablet", "headset", "webcam"),
    "leisure": ("cinema", "netflix", "spotify", "show", "jogo", "bar", "viagem",
                "streaming", "ingresso"),
    "health": ("farmacia", "remedio", "medico", "dentista", "academia", "exame",
               "consulta"),
    "housing": ("aluguel", "luz", "agua", "internet", "condominio", "gas", "iptu"),
    "education": ("curso", "livro", "faculdade", "mensalidade", "apostila"),
    "clothing": ("camisa", "calca", "tenis", "sapato", "roupa", "jaqueta"),
}

_PERIOD_KEYWORDS = (
    ("mes passado", "last_month"),
    ("ultimo mes", "last_month"),
    ("esse mes", "this_month"),
    ("este mes", "this_month"),
    ("no mes", "this_month"),
    ("essa semana", "this_week"),
    ("esta semana", "this_week"),
    ("ultimos 7", "last_7_days"),
    ("ultimos 30", "last_30_days"),
    ("esse ano", "this_year"),
    ("este ano", "this_year"),
    ("anteontem", "day_before_yesterday"),
    ("ontem", "yesterday"),
    ("hoje", "today"),
)

_QUERY_WORDS = ("quanto", "mostra", "mostre", "lista", "liste", "quais", "ver ",
                "veja", "busca", "busque", "exibe", "exiba", "total", "gastos")

_NOISE = {
    "gastei", "gasto", "paguei", "comprei", "reais", "real", "rs", "conto",
    "no", "na", "do", "da", "de", "em", "com", "um", "uma", "uns", "umas",
    "o", "a", "os", "as", "e", "meu", "minha", "pelo", "pela", "por", "pra",
    "para", "cartao", "credito", "debito", "hoje", "ontem", "anteontem",
    "num", "numa", "que", "eu", "mes", "passado", "semana", "ano", "ultimo",
    "esse", "este", "essa", "esta", "dias", "ultimos",
}


def _strip_accents(text):
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def interpret_offline(text, cards, today):
    """Mesmo contrato de saída de interpret(), sem chamar API nenhuma."""
    plain = _strip_accents(text)
    method = "CREDIT" if "credito" in plain else ("DEBIT" if "debito" in plain else "")
    card = _find_card(plain, cards)
    period_label = _find_period(plain)
    amounts = _AMOUNT.findall(plain)

    # "cadastra" já é inequívoco: não exige a palavra "cartão" na frase.
    if re.search(r"\b(cadastr|adicion|registr)a", plain) and not amounts:
        return {"action": "register_card",
                "args": {"cards": _find_new_cards(text, plain)}}

    # Só é um pedido de listagem se ninguém citou um cartão específico —
    # "gastos do cartão Bradesco" é uma busca, e o servidor é quem recusa.
    if (re.search(r"\bcart(ao|oes)\b", plain) and not card and not amounts
            and re.search(r"\b(lista|liste|quais|meus|mostra|mostre|ver|veja)\b", plain)):
        return {"action": "list_cards", "args": {}}

    if "resumo" in plain or "agrupa" in plain:
        return {"action": "summary", "args": {
            "group_by": _find_group(plain), "card": card, "method": method,
            "category": _find_category(plain),
            "period": period_label or "all_time"}}

    if any(word in plain for word in _QUERY_WORDS) and not amounts:
        return {"action": "search_expenses", "args": {
            "card": card, "method": method,
            "category": _find_category(plain),
            "period": period_label or "all_time"}}

    if not amounts:
        return {"action": "unknown",
                "args": {"reason": "no amount found in the command"}}

    # Repassa o rótulo como veio, mesmo sendo de período ("mês passado"): quem
    # o converte numa data única é period.transaction_date. Forçar "today" aqui
    # descartaria a informação e dataria o gasto errado em silêncio.
    return {"action": "register_expense", "args": {
        "product": _find_product(plain, card),
        "description": text.strip(),
        "amount": float(amounts[0].replace(",", ".")),
        "card": card,
        "method": method,
        "category": _find_category(plain) or "other",
        "date_label": period_label,
    }}


def _find_card(plain, cards):
    for name, _ in cards:
        if _strip_accents(name) in plain:
            return name
    # Nenhum cartão conhecido: se o texto nomeia um ("cartão Bradesco"), devolve
    # assim mesmo para que a validação no servidor recuse com uma boa mensagem.
    named = re.search(r"\bcartao\s+([a-z]{3,})", plain)
    return named.group(1).capitalize() if named else ""


# Palavras que aparecem num comando de cadastro sem serem nome de cartão.
_CARD_COMMAND_NOISE = _NOISE | {
    "cadastra", "cadastrar", "cadastro", "adiciona", "adicionar", "registra",
    "registrar", "cartoes", "metodo", "metodos", "funcao", "novo", "nova",
    "favor", "quero", "vamos", "tambem", "ambos", "dois", "como",
}


def _find_new_cards(text, plain):
    """Extrai pares (nome, método) de um comando de cadastro.

    Heurística: palavras capitalizadas no texto original são nomes de cartão; o
    método vem da palavra crédito/débito mais próxima à direita.
    """
    names = re.findall(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]{2,})", text)
    if not names:
        # Comando todo em minúsculas ("cadastra o itau no debito"): sobra o que
        # não for ruído. Sem isto o cadastro falhava calado, devolvendo [].
        names = [word.capitalize()
                 for word in re.findall(r"[a-zà-ÿ]{3,}", plain)
                 if word not in _CARD_COMMAND_NOISE]
    if not names:
        return []
    found = []
    for name in names:
        start = plain.find(_strip_accents(name))
        chunk = plain[start:]
        # Método(s) citados antes do próximo nome de cartão.
        for other in names:
            if other == name:
                continue
            cut = chunk.find(_strip_accents(other))
            if cut > 0:
                chunk = chunk[:cut]
        methods = []
        if "credito" in chunk:
            methods.append("CREDIT")
        if "debito" in chunk:
            methods.append("DEBIT")
        for method in methods or ["CREDIT"]:
            found.append({"name": name, "method": method})
    return found


def _find_period(plain):
    for keyword, label in _PERIOD_KEYWORDS:
        if keyword in plain:
            return label
    return ""


def _find_category(plain):
    # Palavra inteira, não substring: sem \b, "gastei" casaria com "gas"
    # e classificaria qualquer comando como housing.
    def has(word):
        return re.search(r"\b%s(s|es)?\b" % re.escape(word), plain) is not None

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(has(keyword) for keyword in keywords):
            return category
    for category in CATEGORIES:
        if has(category):
            return category
    return ""


def _find_group(plain):
    if "metodo" in plain or "credito" in plain or "debito" in plain:
        return "method"
    if "cartao" in plain or "cartoes" in plain:
        return "card"
    return "category"


def _find_product(plain, card):
    without_card = plain.replace(_strip_accents(card), " ") if card else plain
    without_amount = _AMOUNT.sub(" ", without_card)
    words = [w for w in re.findall(r"[a-z]+", without_amount) if w not in _NOISE]
    return " ".join(words[:4]) or "expense"


def _list_models():
    for model in _client().models.list():
        # A API lista o id datado (claude-haiku-4-5-20251001); o .env costuma
        # usar o apelido sem data, que também é válido nas chamadas.
        marker = " <- em uso" if model.id.startswith(model_name()) else ""
        print("%-28s %s%s" % (model.id, model.display_name, marker))


if __name__ == "__main__":
    if "--models" in sys.argv:
        # Rodando solto, este módulo não passa pelo load_env() do client.py.
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        except ImportError:
            pass
        _list_models()
    else:
        print(__doc__)
