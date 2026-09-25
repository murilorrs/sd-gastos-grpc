"""O que os dois microsserviços gRPC têm em comum: rótulos, log e o arranque."""

import argparse
import logging
import os
from concurrent import futures

import grpc

import expenses_pb2

METHOD_LABEL = {
    expenses_pb2.METHOD_UNSPECIFIED: "any",
    expenses_pb2.CREDIT: "credit",
    expenses_pb2.DEBIT: "debit",
}

log = logging.getLogger("service")


def log_rpc(context, method, detail):
    """O log que prova a comunicação durante a apresentação."""
    log.info("%-16s from %-24s %s", method, context.peer(), detail)


def serve(name, create_server, default_port, default_database):
    """Lê os argumentos, escolhe o banco e mantém o servidor no ar.

    O banco é PostgreSQL quando PGHOST está no ambiente (a VM, falando com o
    Cloud SQL pelo IP privado) e SQLite caso contrário (desenvolvimento local).

    O host padrão é 127.0.0.1: os serviços gRPC só aceitam conexões da própria
    máquina, e a única porta de entrada do sistema é o Gateway. Firewall não
    bastaria para isso — a regra default-allow-internal do GCP libera todas as
    portas entre VMs da VPC.
    """
    parser = argparse.ArgumentParser(description="%s - gRPC microservice" % name)
    parser.add_argument("--host", default=os.environ.get("GRPC_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--database", default=default_database,
                        help="SQLite file, used only when PGHOST is not set")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")

    if os.environ.get("PGHOST"):
        db_path = None
        db_label = "postgres %s/%s" % (os.environ["PGHOST"],
                                       os.environ.get("PGDATABASE", ""))
    else:
        db_path = db_label = args.database

    server, port = create_server(db_path, "%s:%d" % (args.host, args.port))
    server.start()
    log.info("%s listening on %s:%d (database: %s)", name, args.host, port, db_label)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=1)


def new_server():
    return grpc.server(futures.ThreadPoolExecutor(max_workers=10))
