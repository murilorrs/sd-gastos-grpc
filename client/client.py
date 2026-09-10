#!/usr/bin/env python3
"""Microsserviço A — cliente gRPC com entrada em linguagem natural.

Fluxo de cada comando digitado:

    texto  ->  Claude (nlu.py)  ->  {"action", "args"}
                                        |
                                        v
                             ValidateCard (RPC)  <- barra cartão inventado
                                        |
                                        v
          RegisterExpense / SearchExpenses / SummaryByGroup (RPC)

O servidor não sabe que existe uma LLM: ele só recebe mensagens do
proto/expenses.proto.
"""

import argparse
import os
import sys
import time
import warnings
from datetime import date

import grpc

import expenses_pb2
import expenses_pb2_grpc
import nlu
import period

METHOD_ENUM = {
    "": expenses_pb2.METHOD_UNSPECIFIED,
    "CREDIT": expenses_pb2.CREDIT,
    "DEBIT": expenses_pb2.DEBIT,
}
METHOD_LABEL = {
    expenses_pb2.METHOD_UNSPECIFIED: "-",
    expenses_pb2.CREDIT: "credit",
    expenses_pb2.DEBIT: "debit",
}
METHODS = (expenses_pb2.CREDIT, expenses_pb2.DEBIT)

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


class App:
    def __init__(self, stub, offline=False, show_bytes=False, verbose=False):
        self.stub = stub
        self.offline = offline
        self.show_bytes = show_bytes
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
        response = self.stub.ListCards(expenses_pb2.ListCardsRequest())
        self.cards = [(c.name, list(c.methods)) for c in response.cards]

    def _labeled_cards(self):
        """Formato que o prompt do modelo espera: métodos como texto."""
        return [(name, [METHOD_LABEL[m] for m in methods])
                for name, methods in self.cards]

    def _methods_of(self, name):
        for registered, methods in self.cards:
            if registered.lower() == name.lower():
                return methods
        return []

    def _dump_bytes(self, message, label):
        if not self.show_bytes:
            return
        raw = message.SerializeToString()
        print("    [%s] %d bytes: %r" % (label, len(raw), raw))

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

        Segunda camada contra alucinação: pergunta ao servidor antes de agir.
        Quando o cartão não confere, em vez de só recusar, oferece ao usuário
        corrigir para um cartão existente ou cadastrar o novo e lançar nele.

        Retorna (name, method), ou None se o usuário cancelar.
        """
        request = expenses_pb2.ValidateCardRequest(name=name, method=method)
        self._dump_bytes(request, "ValidateCardRequest")
        validation = self.stub.ValidateCard(request)

        if validation.exists:
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

        print("  x %s" % validation.message)
        choice = self._ask(
            "how do you want to proceed?",
            self._alternatives(name, method, validation, for_registration))
        if choice is None:
            return None
        if len(choice) == 3:  # ("name", method, "create")
            new_name, new_method, _ = choice
            response = self.stub.RegisterCard(expenses_pb2.RegisterCardRequest(
                name=new_name, method=new_method))
            print("  + %s" % response.message)
            self.reload_cards()
            return new_name, new_method
        return choice

    def _alternatives(self, name, method, validation, for_registration):
        """Monta o menu de recuperação a partir das sugestões do servidor."""
        base = [(c.name, list(c.methods)) for c in validation.suggestions] or self.cards
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
        for item in args.get("cards", []):
            request = expenses_pb2.RegisterCardRequest(
                name=item.get("name", ""),
                method=METHOD_ENUM.get(item.get("method", ""), 0),
            )
            self._dump_bytes(request, "RegisterCardRequest")
            response = self.stub.RegisterCard(request)
            print("  + %s" % response.message)
        self.reload_cards()

    def list_cards(self, args):
        if not self.cards:
            print("  no cards registered")
            return
        for name, methods in self.cards:
            print("  %-14s %s" % (name, ", ".join(METHOD_LABEL[m] for m in methods)))

    def register_expense(self, args):
        # Checagens locais antes de qualquer RPC: erram rápido, respondem numa
        # linha e não gastam uma ida ao servidor para dizer o óbvio.
        amount = float(args.get("amount") or 0)
        if amount <= 0:
            print("  x missing amount — say how much it cost")
            return
        if not args.get("product", "").strip():
            print("  x missing product — say what you bought")
            return

        method = METHOD_ENUM.get(args.get("method", ""), 0)
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
        request = expenses_pb2.RegisterExpenseRequest(
            product=args.get("product", ""),
            description=args.get("description", ""),
            amount=amount,
            card=card,
            method=method,
            category=args.get("category", ""),
            date=args.get("date") or period.transaction_date(label),
        )
        self._dump_bytes(request, "RegisterExpenseRequest")
        response = self.stub.RegisterExpense(request)
        if not response.ok:
            print("  x %s" % response.message)
            return
        e = response.expense
        print("  + #%d  %s  %.2f  %s/%s  [%s]  %s" % (
            e.id, e.product, e.amount, e.card, METHOD_LABEL[e.method],
            e.category, e.date))

    def search_expenses(self, args):
        filters = self._build_filter(args)
        if filters.card:
            resolved = self._resolve_card(
                filters.card, filters.method, for_registration=False)
            if resolved is None:
                print("  search cancelled")
                return
            filters.card, filters.method = resolved
        self._dump_bytes(filters, "Filter")

        total = 0.0
        count = 0
        # Server-streaming: cada gasto chega assim que o servidor o encontra.
        for e in self.stub.SearchExpenses(filters):
            print("  #%-4d %-24s %10.2f  %-10s %-7s %-11s %s" % (
                e.id, e.product[:24], e.amount, e.card,
                METHOD_LABEL[e.method], e.category, e.date))
            total += e.amount
            count += 1
        if count:
            print("  %s\n  %d expense(s), total %.2f" % ("-" * 74, count, total))
        else:
            print("  no expenses match those filters")

    def summary(self, args):
        filters = self._build_filter(args)
        if filters.card:
            resolved = self._resolve_card(
                filters.card, filters.method, for_registration=False)
            if resolved is None:
                print("  summary cancelled")
                return
            filters.card, filters.method = resolved
        request = expenses_pb2.SummaryRequest(
            group_by=args.get("group_by") or "category", filter=filters)
        self._dump_bytes(request, "SummaryRequest")
        response = self.stub.SummaryByGroup(request)
        if not response.totals:
            print("  no expenses match those filters")
            return
        for t in response.totals:
            print("  %-16s %11.2f  (%d)" % (t.key, t.total, t.count))
        print("  %s\n  %-16s %11.2f" % ("-" * 42, "TOTAL", response.grand_total))

    def unknown(self, args):
        print("  ? %s" % args.get("reason", "command not understood"))
        print("    type :help for examples")

    def _build_filter(self, args):
        start, end = period.resolve(args.get("period", ""))
        return expenses_pb2.Filter(
            card=args.get("card", ""),
            method=METHOD_ENUM.get(args.get("method", ""), 0),
            category=args.get("category", ""),
            start_date=args.get("start_date") or start,
            end_date=args.get("end_date") or end,
        )

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
        except grpc.RpcError as error:
            print("  x server error [%s]: %s" % (error.code().name, error.details()))
        grpc_seconds = time.perf_counter() - started

        # A comparação que vale a pena mostrar na apresentação: o gRPC não é o
        # gargalo — a chamada à LLM é ordens de magnitude mais lenta.
        if self.verbose:
            print("  . nlu %.0f ms . grpc %.0f ms" % (
                nlu_seconds * 1000, grpc_seconds * 1000))


def repl(app, address):
    print("gRPC client connected to %s%s" % (
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
            app.show_bytes = not app.show_bytes
            print("  byte dump: %s" % ("on" if app.show_bytes else "off"))
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
    parser = argparse.ArgumentParser(description="Microservice A - gRPC client")
    parser.add_argument("--server", default="localhost:50051",
                        help="host:port of Microservice B")
    parser.add_argument("--offline", action="store_true",
                        help="interpret with local rules, without calling the LLM")
    parser.add_argument("--verbose", action="store_true",
                        help="show the structured command and the timings")
    parser.add_argument("--bytes", action="store_true",
                        help="print the serialized protobuf of each request")
    parser.add_argument("--command", help="run a single command and exit")
    args = parser.parse_args()

    silence_known_warnings()
    load_env()
    channel = grpc.insecure_channel(args.server)
    try:
        # Falha rápido e com mensagem clara se o servidor não estiver de pé.
        grpc.channel_ready_future(channel).result(timeout=5)
    except grpc.FutureTimeoutError:
        print("could not connect to %s" % args.server, file=sys.stderr)
        print("is Microservice B running? is port 50051 open?", file=sys.stderr)
        return 1

    stub = expenses_pb2_grpc.ExpenseServiceStub(channel)
    app = App(stub, offline=args.offline, show_bytes=args.bytes,
              verbose=args.verbose)
    if args.command:
        app.run_command(args.command)
    else:
        repl(app, args.server)
    channel.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
