#!/usr/bin/env bash
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" -m controller --url "$SIM_URL" --db "${CONTROLLER_DB:-runs/controller.sqlite}"
