#!/usr/bin/env bash
# Run against an already-started, fresh simulator. Example:
# CONTROLLER_DB=runs/crash.sqlite PYTHON=.venv/bin/python scripts/crash_recovery.sh http://127.0.0.1:8700
set -euo pipefail
SIM_URL="${1:?usage: crash_recovery.sh SIM_URL}"
DB="${CONTROLLER_DB:-runs/crash.sqlite}"
if [ -n "${PYTHON:-}" ]; then
    :
elif [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python3
fi

CONTROLLER_DB="$DB" PYTHON="$PYTHON" ./run.sh "$SIM_URL" > runs/crash_first.log 2>&1 &
pid=$!
killed=false
for _ in $(seq 1 500); do
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "controller exited before kill point; see runs/crash_first.log" >&2
        wait "$pid" 2>/dev/null || true
        exit 1
    fi
    minute=$(curl -fsS "$SIM_URL/sim/state" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["sim_minute"])')
    if [ "$minute" -ge 600 ]; then
        kill -9 "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        killed=true
        break
    fi
    sleep 0.01
done
if [ "$killed" != true ]; then
    echo "controller did not reach D0 10:00 in time" >&2
    kill -9 "$pid" 2>/dev/null || true
    exit 1
fi
echo "killed controller at simulated minute $minute"
CONTROLLER_DB="$DB" PYTHON="$PYTHON" ./run.sh "$SIM_URL" > runs/crash_restart.log 2>&1
curl -fsS "$SIM_URL/sim/state" | "$PYTHON" -c 'import json,sys; s=json.load(sys.stdin); assert s["finished"], s; print("restart finished at minute",s["sim_minute"])'
"$PYTHON" - "$DB" "$SIM_URL" <<'PY'
import json, sqlite3, sys, urllib.request
c = sqlite3.connect(sys.argv[1])
print("chunks:", c.execute("select count(*) from chunks").fetchone()[0])
print("pending intents:", c.execute("select count(*) from intents where status in ('prepared','pending','approved')").fetchone()[0])
def get(path):
    with urllib.request.urlopen(sys.argv[2] + path) as response:
        return json.load(response)
applied = {row[0] for row in c.execute("select proposal_id from intents where status='applied'")}
actual = []
for wf in get("/workflows"):
    actual += [row["proposal_id"] for row in get(f"/workflows/{wf['workflow_id']}/config/history") if row.get("proposal_id")]
duplicates = len(actual) - len(set(actual))
print("duplicate config applications:", duplicates)
print("applied intents matched in config history:", len(applied & set(actual)), "/", len(applied))
assert duplicates == 0
assert applied <= set(actual)
PY
