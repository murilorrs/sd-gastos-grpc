#!/usr/bin/env bash
# Gera os stubs Python a partir de proto/gastos.proto.
#
# Os stubs vão para servidor/ e cliente/ (arquivos duplicados, mas gerados) para
# que cada serviço rode sem nenhum ajuste de sys.path. Eles ficam fora do git:
# rode este script sempre que mexer no .proto.
set -euo pipefail
cd "$(dirname "$0")"

for destino in servidor cliente; do
  python -m grpc_tools.protoc \
    -I proto \
    --python_out="$destino" \
    --grpc_python_out="$destino" \
    proto/gastos.proto
  echo "stubs gerados em $destino/"
done
