# Imagem dos três processos Python: os dois microsserviços gRPC e o Gateway.
#
# Uma imagem só, três comandos diferentes — eles compartilham o .proto, os
# stubs gerados e as dependências. O processo que cada container sobe está no
# docker-compose.yml.
FROM python:3.12-slim

WORKDIR /app

# As dependências mudam menos que o código: instalá-las antes de copiar o
# resto aproveita o cache de camadas em toda reconstrução.
COPY server/requirements.txt /tmp/server.txt
COPY gateway/requirements.txt /tmp/gateway.txt
# anthropic entra aqui porque o Gateway interpreta linguagem natural; sem a
# chave no ambiente, ele nunca é chamado.
RUN pip install --no-cache-dir -q -r /tmp/server.txt -r /tmp/gateway.txt anthropic

COPY proto/ ./proto/
COPY server/ ./server/
COPY gateway/ ./gateway/
COPY language/ ./language/
COPY generate_stubs.sh ./

# Os stubs não são versionados: cada build os recria a partir do .proto, o que
# torna impossível rodar com stub dessincronizado do contrato.
RUN bash generate_stubs.sh

ENV PYTHONUNBUFFERED=1
