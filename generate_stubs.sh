#!/usr/bin/env bash
# Gera os stubs Python a partir de proto/expenses.proto.
#
# Quem fala gRPC: os microsserviços (server/) e o Gateway (gateway/). O cliente
# de terminal fala HTTP com o Gateway e não precisa deles.
#
# Os stubs ficam duplicados em cada pasta para que cada componente rode sem
# ajuste de sys.path. Eles ficam fora do git: rode este script sempre que
# mexer no .proto.
set -euo pipefail
cd "$(dirname "$0")"

for target in server gateway; do
  python -m grpc_tools.protoc \
    -I proto \
    --python_out="$target" \
    --grpc_python_out="$target" \
    proto/expenses.proto
  echo "stubs generated in $target/"
done
