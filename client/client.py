#!/usr/bin/env python3
"""Cliente de terminal com entrada em linguagem natural.

Fala só com o API Gateway, por HTTP/JSON e com um JWT — nunca direto com os
microsserviços gRPC, que nem aceitam conexões de fora da vm-server.

Fluxo de cada comando digitado:

    texto  ->  Claude (nlu.py)  ->  {"action", "args"}
                                        |
                                        v  HTTP/JSON + Authorization: Bearer
                          GET /cards/validate    <- barra cartão inventado
                                        |
                                        v
              POST /expenses  |  GET /expenses  |  GET /expenses/summary

O Gateway traduz cada chamada para gRPC. Nenhum serviço atrás dele sabe que
existe uma LLM.
"""

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import date

import nlu
import period

METHOD_LABEL = {"": "-", None: "-", "CREDIT": "credit", "DEBIT": "debit"}
METHODS = ("CREDIT", "DEBIT")

HELP = """
Type commands in Portuguese. Examples:

  cadastra o Nubank no crédito e no débito
  gastei 89 reais num teclado mecânico no crédito do Nubank
  almoço de 42 reais no débito do Itaú ontem
  me mostra tudo que eu gastei no Nubank no crédito esse mês
  quanto gastei em tecnologia?
  resumo por método

Terminal commands:  :help   :cards   :verbose   :bytes   :clear   :quit
"""


class GatewayError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Gateway:
    """Cliente HTTP mínimo do API Gateway, com login e renovação do JWT."""

    def __init__(self, base_url, username, password, show_payload=False):
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token = None
        self.show_payload = show_payload

    def login(self):
        data = self.request("POST", "/auth/token",
                            {"username": self._username, "password": self._password},
                            auth=False)
        self._token = data["access_token"]

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body):
        return self.request("POST", path, body)

    def request(self, method, path, body=None, params=None, auth=True, retry=True):
        url = self.base_url + path
        if params:
            query = {k: v for k, v in params.items() if v not in ("", None)}
            if query:
                url += "?" + urllib.parse.urlencode(query)
        payload = None if body is None else json.dumps(body).encode()

        if self.show_payload and auth:
            shown = "%s %s" % (method, url[len(self.base_url):])
            if payload:
                shown += "  %d bytes JSON: %s" % (len(payload), payload.decode())
            print("    [http] %s" % shown)

        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", "Bearer %s" % self._token)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            # O token vence em uma hora: renova uma vez e repete a chamada, em
            # vez de derrubar uma sessão longa (a apresentação, por exemplo).
            if error.code == 401 and auth and retry:
                self.login()
                return self.request(method, path, body, params, auth, retry=False)
            try:
                detail = json.loads(error.read()).get("detail", error.reason)
            except ValueError:
                detail = error.reason
            raise GatewayError(error.code, detail)


class App:
    def __init__(self, gateway, offline=False, verbose=False):
        self.gateway = gateway
        self.offline = offline
        # Desligado por padrão: o uso normal quer ver só o resultado. Ligue com
        # :verbose para a apresentação, onde o comando estruturado e os tempos
        # são justamente o que se quer mostrar.
        self.verbose = verbose
        self.cards = []
        self.reload_cards()

    # ---------- plumbing ----------

    def reload_cards(self):
        """Alimenta o prompt do modelo com os cartões que existem de verdade.

        Primeira das três camadas contra alucinação: o modelo escolhe dentro de
        uma lista real em vez de inventar um nome.
        """
        cards = self.gateway.get("/cards")["cards"]
        self.cards = [(c["name"], c["methods"]) for c in cards]

    def _labeled_cards(self):
        """Formato que o prompt do modelo espera: métodos como texto."""
        return [(name, [METHOD_LABEL[m] for m in methods])
                for name, methods in self.cards]

    def _methods_of(self, name):
        for registered, methods in self.cards:
            if registered.lower() == name.lower():
                return methods
        return []

    # ---------- card resolution ----------

    def _ask(self, title, options):
        """Menu numerado. `options` é [(label, value)]. None = cancelado.

        Sem terminal interativo (stdin redirecionado), o EOFError cai em
        cancelamento — o comando não é executado pela metade.
        """
        print("  %s" % title)
        for number, (label, _) in enumerate(options, 1):
            print("    %d) %s" % (number, label))
        print("    0) cancel")
        while True:
            try:
                choice = input("  choice> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if choice in ("0", "", "c", "cancel"):
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                return options[int(choice) - 1][1]
            print("  enter a number from 0 to %d" % len(options))

    def _resolve_card(self, name, method, for_registration):
        """Garante um par (cartão, método) que existe de verdade.

        Segunda camada contra alucinação: pergunta ao sistema antes de agir.
        Quando o cartão não confere, em vez de só recusar, oferece ao usuário
        corrigir para um cartão existente ou cadastrar o novo e lançar nele.

        Retorna (name, method), ou None se o usuário cancelar.
        """
        validation = self.gateway.get("/cards/validate",
                                      {"name": name, "method": method or None})

        if validation["exists"]:
            name = validation["name"] or name
            if method:
                return name, method
            methods = self._methods_of(name)
            # Numa busca, método vazio significa "qualquer um" — não há o que
            # perguntar. Num registro, é preciso saber crédito ou débito.
            if not for_registration:
                return name, method
            if len(methods) == 1:
                return name, methods[0]
            return self._ask(
                "was %s credit or debit?" % name,
                [("%s (%s)" % (name, METHOD_LABEL[m]), (name, m)) for m in methods])

        print("  x %s" % validation["message"])
        choice = self._ask(
            "how do you want to proceed?",
            self._alternatives(name, method, validation, for_registration))
        if choice is None:
            return None
        if len(choice) == 3:  # ("name", method, "create")
            new_name, new_method, _ = choice
            response = self.gateway.post("/cards",
                                         {"name": new_name, "method": new_method})
            print("  + %s" % response["message"])
            self.reload_cards()
            return new_name, new_method
        return choice

    def _alternatives(self, name, method, validation, for_registration):
        """Monta o menu de recuperação a partir das sugestões do servidor."""
        base = ([(c["name"], c["methods"]) for c in validation["suggestions"]]
                or self.cards)
        options = [
            ("use %s (%s)" % (registered, METHOD_LABEL[m]), (registered, m))
            for registered, methods in base
            for m in methods
        ]
        if not for_registration:
            return options

        # No registro dá para criar o que falta e lançar direto nele. Se o
        # usuário disse o método, só esse; senão, os dois.
        already = self._methods_of(name)
        for candidate in ([method] if method else METHODS):
            if candidate in already:
                continue
            options.append((
                "register %s for %s and record it there" % (
                    name, METHOD_LABEL[candidate]),
                (name, candidate, "create"),
            ))
        return options

    # ---------- actions ----------

    def register_card(self, args):
        if not args.get("cards"):
            print("  x missing card name — try: cadastra o Nubank no crédito")
            return
        for item in args["cards"]:
            response = self.gateway.post("/cards", {"name": item.get("name", ""),
                                                    "method": item.get("method", "")})
            print("  + %s" % response["message"])
        self.reload_cards()

    def list_cards(self, args):
        if not self.cards:
            print("  no cards registered")
            return
        for name, methods in self.cards:
            print("  %-14s %s" % (name, ", ".join(METHOD_LABEL[m] for m in methods)))

    def register_expense(self, args):
        # Checagens locais antes de qualquer chamada: erram rápido, respondem
        # numa linha e não gastam uma ida ao servidor para dizer o óbvio. O
        # Gateway valida tudo de novo — ele não pode confiar em quem chama.
        amount = float(args.get("amount") or 0)
        if amount <= 0:
            print("  x missing amount — say how much it cost")
            return
        if not args.get("product", "").strip():
            print("  x missing product — say what you bought")
            return

        method = args.get("method") or ""
        card = args.get("card", "")
        if not card:
            print("  x missing card — try: no crédito do Nubank")
            return
        resolved = self._resolve_card(card, method, for_registration=True)
        if resolved is None:
            print("  cancelled, nothing was saved")
            return
        card, method = resolved

        # O modelo às vezes põe o tempo em "period" mesmo num registro, apesar
        # do prompt. Aceitar os dois campos evita datar o gasto como hoje por
        # causa de um nome de campo — um erro que passaria despercebido.
        label = args.get("date_label") or args.get("period")
        body = {
            "product": args.get("product", ""),
            "description": args.get("description", ""),
            "amount": amount,
            "card": card,
            "method": method,
            "category": args.get("category") or "other",
            "date": args.get("date") or period.transaction_date(label),
        }
        e = self.gateway.post("/expenses", body)["expense"]
        print("  + #%d  %s  %.2f  %s/%s  [%s]  %s" % (
            e["id"], e["product"], e["amount"], e["card"],
            METHOD_LABEL[e["method"]], e["category"], e["date"]))

    def _resolved_filter(self, args, what):
        """Filtro da busca/resumo, com o cartão conferido. None = cancelado."""
        filters = self._build_filter(args)
        if filters["card"]:
            resolved = self._resolve_card(filters["card"], filters["method"],
                                          for_registration=False)
            if resolved is None:
                print("  %s cancelled" % what)
                return None
            filters["card"], filters["method"] = resolved
        return filters

    def search_expenses(self, args):
        filters = self._resolved_filter(args, "search")
        if filters is None:
            return
        # Entre o Gateway e o serviço de Gastos isto é um stream gRPC; o
        # Gateway junta os itens e devolve uma lista JSON.
        found = self.gateway.get("/expenses", filters)["expenses"]
        for e in found:
            print("  #%-4d %-24s %10.2f  %-10s %-7s %-11s %s" % (
                e["id"], e["product"][:24], e["amount"], e["card"],
                METHOD_LABEL[e["method"]], e["category"], e["date"]))
        if found:
            print("  %s\n  %d expense(s), total %.2f" % (
                "-" * 74, len(found), sum(e["amount"] for e in found)))
        else:
            print("  no expenses match those filters")

    def summary(self, args):
        filters = self._resolved_filter(args, "summary")
        if filters is None:
            return
        filters["group_by"] = args.get("group_by") or "category"
        response = self.gateway.get("/expenses/summary", filters)
        if not response["totals"]:
            print("  no expenses match those filters")
            return
        for t in response["totals"]:
            print("  %-16s %11.2f  (%d)" % (t["key"], t["total"], t["count"]))
        print("  %s\n  %-16s %11.2f" % ("-" * 42, "TOTAL", response["grand_total"]))

    def unknown(self, args):
        print("  ? %s" % args.get("reason", "command not understood"))
        print("    type :help for examples")

    def _build_filter(self, args):
        start, end = period.resolve(args.get("period", ""))
        return {
            "card": args.get("card", ""),
            "method": args.get("method") or "",
            "category": args.get("category", ""),
            "start_date": args.get("start_date") or start,
            "end_date": args.get("end_date") or end,
        }

    # ---------- main loop ----------

    def run_command(self, text):
        today = date.today().isoformat()
        started = time.perf_counter()
        try:
            cards = self._labeled_cards()
            if self.offline:
                command = nlu.interpret_offline(text, cards, today)
            else:
                command = nlu.interpret(text, cards, today)
        except Exception as error:  # a API caiu, sem cota, sem rede
            print("  ! LLM indisponível — %s; usando o modo offline"
                  % nlu.explain(error))
            command = nlu.interpret_offline(text, self._labeled_cards(), today)
        nlu_seconds = time.perf_counter() - started

        action = command.get("action", "unknown")
        args = command.get("args", {})
        if self.verbose:
            # Só os campos preenchidos: metade dos args vem vazia e a linha
            # fica ilegível justamente quando ela é o que se quer mostrar.
            filled = {k: v for k, v in args.items()
                      if v not in ("", 0, None, [], {})}
            print("  -> %s %s" % (action, filled))

        handler = {
            "register_card": self.register_card,
            "list_cards": self.list_cards,
            "register_expense": self.register_expense,
            "search_expenses": self.search_expenses,
            "summary": self.summary,
        }.get(action, self.unknown)

        started = time.perf_counter()
        try:
            handler(args)
        except GatewayError as error:
            print("  x [%d] %s" % (error.status, error.detail))
        except urllib.error.URLError as error:
            print("  x gateway unreachable: %s" % error.reason)
        gateway_seconds = time.perf_counter() - started

        # A comparação que vale a pena mostrar na apresentação: HTTP + gRPC
        # juntos ainda são muito mais rápidos que a chamada à LLM.
        if self.verbose:
            print("  . nlu %.0f ms . gateway %.0f ms" % (
                nlu_seconds * 1000, gateway_seconds * 1000))


def repl(app, address):
    print("connected to gateway %s%s" % (
        address, "  [offline mode]" if app.offline else ""))
    print(HELP)
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text in (":quit", ":q", "quit"):
            return
        if text == ":help":
            print(HELP)
            continue
        if text in (":clear", ":cls"):
            # 2J limpa a tela, 3J o histórico de rolagem, H volta o cursor ao
            # topo. Sequências ANSI: não dependem de `clear` nem de subprocesso.
            print("\033[2J\033[3J\033[H", end="")
            continue
        if text == ":cards":
            app.reload_cards()
            app.list_cards({})
            continue
        if text in (":verbose", ":v"):
            app.verbose = not app.verbose
            print("  verbose: %s" % ("on" if app.verbose else "off"))
            continue
        if text == ":bytes":
            app.gateway.show_payload = not app.gateway.show_payload
            print("  payload dump: %s" % ("on" if app.gateway.show_payload else "off"))
            continue
        app.run_command(text)


def silence_known_warnings():
    """Cala avisos que não indicam problema, para a saída ficar legível.

    O urllib3 reclama que o macOS compila o módulo ssl contra LibreSSL em vez
    de OpenSSL. É do ambiente local; na VM (Debian 12) nem aparece.

    Fica só aqui, no ponto de entrada da CLI. Nenhum módulo mexe em warnings.
    """
    warnings.filterwarnings("ignore", message=".*OpenSSL.*")


def load_env():
    """Lê o .env da raiz do repositório, se o python-dotenv estiver instalado."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(root, ".env"))


def main():
    silence_known_warnings()
    load_env()

    parser = argparse.ArgumentParser(description="Terminal client for the API gateway")
    parser.add_argument("--gateway",
                        default=os.environ.get("GATEWAY_URL", "http://localhost:8000"),
                        help="base URL of the API gateway")
    parser.add_argument("--offline", action="store_true",
                        help="interpret with local rules, without calling the LLM")
    parser.add_argument("--verbose", action="store_true",
                        help="show the structured command and the timings")
    parser.add_argument("--bytes", action="store_true",
                        help="print the JSON sent to the gateway on each request")
    parser.add_argument("--command", help="run a single command and exit")
    args = parser.parse_args()

    username = os.environ.get("GATEWAY_USER") or input("gateway user: ")
    password = os.environ.get("GATEWAY_PASSWORD") or getpass.getpass("password: ")
    gateway = Gateway(args.gateway, username, password, show_payload=args.bytes)
    try:
        gateway.login()
        app = App(gateway, offline=args.offline, verbose=args.verbose)
    except GatewayError as error:
        print("login failed [%d]: %s" % (error.status, error.detail), file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print("could not reach the gateway at %s (%s)" % (args.gateway, error.reason),
              file=sys.stderr)
        print("is the gateway running? is port 8000 open?", file=sys.stderr)
        return 1

    if args.command:
        app.run_command(args.command)
    else:
        repl(app, args.gateway)
    return 0


if __name__ == "__main__":
    sys.exit(main())
