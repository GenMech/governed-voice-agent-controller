#!/usr/bin/env bash
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
if [ -n "${PYTHON:-}" ]; then
    :
elif [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi
exec "$PYTHON" -m controller --url "$SIM_URL" --db "${CONTROLLER_DB:-runs/controller.sqlite}"
