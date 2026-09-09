#!/usr/bin/env bash
# Gera os stubs Python a partir de proto/expenses.proto.
#
# Os stubs vão para server/ e client/ (arquivos duplicados, mas gerados) para
# que cada serviço rode sem nenhum ajuste de sys.path. Eles ficam fora do git:
# rode este script sempre que mexer no .proto.
set -euo pipefail
cd "$(dirname "$0")"

for target in server client; do
  python -m grpc_tools.protoc \
    -I proto \
    --python_out="$target" \
    --grpc_python_out="$target" \
    proto/expenses.proto
  echo "stubs generated in $target/"
done
