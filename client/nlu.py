#!/usr/bin/env python3
"""Microsserviço A — camada de linguagem natural.

Transforma o texto do usuário num comando estruturado. Nada aqui fala gRPC: a
saída é um dict {"action": ..., "args": {...}} que o client.py despacha.

Usa saída JSON estruturada em vez de function calling. Faz o mesmo trabalho
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

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK_MODEL = os.environ.get("GEMINI_MODEL_FALLBACK", "gemini-3.5-flash-lite")

TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "15000"))

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
   que não existe nesta ação. Valores aceitos: "today", "yesterday",
   "day_before_yesterday". Use "date": "AAAA-MM-DD" apenas quando o texto
   disser uma data explícita ("dia 3", "12/08").

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


_genai_client = None


def _client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and fill "
                "it in, or run the client with --offline.")
        _genai_client = genai.Client(
            api_key=key, http_options={"timeout": TIMEOUT_MS})
    return _genai_client


_RETRYABLE = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL")


def _retryable(error):
    return any(mark in str(error) for mark in _RETRYABLE)


def interpret(text, cards, today, model=None):
    """Texto -> {"action": ..., "args": {...}} usando o Gemini.

    `cards` é [(name, [rótulos de método])], vindo do RPC ListCards.

    Tenta o modelo principal e, se ele estiver sobrecarregado, o reserva. Só
    levanta o erro se nenhuma tentativa der certo — aí o client.py cai no
    interpretador offline.
    """
    prompt = build_prompt(text, cards, today)
    models = [model] if model else [DEFAULT_MODEL, FALLBACK_MODEL]
    last_error = None

    for name in models:
        for delay in (0, 1.5):
            if delay:
                time.sleep(delay)
            try:
                response = _client().models.generate_content(
                    model=name,
                    contents=prompt,
                    config={"response_mime_type": "application/json",
                            "temperature": 0},
                )
                return _load_json(response.text)
            except Exception as error:
                last_error = error
                if not _retryable(error):
                    break  # problema do modelo, não da carga: vai para o próximo

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
# risco do projeto, que é a API do Gemini estar fora do ar, sem quota ou
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
                   "ssd", "cabo", "carregador", "computador"),
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


def _find_new_cards(text, plain):
    """Extrai pares (nome, método) de um comando de cadastro.

    Heurística: palavras capitalizadas no texto original são nomes de cartão; o
    método vem da palavra crédito/débito mais próxima à direita.
    """
    names = re.findall(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]{2,})", text)
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
        print(model.name)


if __name__ == "__main__":
    if "--models" in sys.argv:
        _list_models()
    else:
        print(__doc__)
