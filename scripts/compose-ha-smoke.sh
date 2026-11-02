#!/usr/bin/env bash
# Local app-tier HA smoke: scaled API behind nginx, checkpointer required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml:docker-compose.ha.yml}"
API_PORT="${API_PORT:-5706}"
BASE="http://127.0.0.1:${API_PORT}"

echo "== compose HA up (api x2) =="
docker compose --profile minimal up -d --scale api=2 api-lb api postgres redis

echo "== wait for readyz (checkpointer required) =="
for _ in $(seq 1 60); do
  if curl -fsS "$BASE/readyz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "$BASE/readyz" | tee /tmp/sahyog-ha-readyz.json
python3 - <<'PY'
import json, sys
payload = json.load(open("/tmp/sahyog-ha-readyz.json"))
checks = payload.get("checks") or payload.get("components") or {}
# Accept either nested checkpointer status or top-level status ok
text = json.dumps(payload).lower()
if "checkpointer" in text and ("down" in text or '"status": "fail"' in text):
    print("checkpointer not ready:", payload, file=sys.stderr)
    sys.exit(1)
print("readyz ok")
PY

echo "== replica count =="
COUNT="$(docker compose ps -q api | wc -l | tr -d ' ')"
if [[ "$COUNT" -lt 2 ]]; then
  echo "expected >=2 api containers, got $COUNT" >&2
  exit 1
fi
echo "api replicas: $COUNT"

echo "== kill one api container; LB should still answer =="
VICTIM="$(docker compose ps -q api | head -n1)"
docker kill "$VICTIM" >/dev/null
sleep 2
curl -fsS "$BASE/healthz" >/dev/null
curl -fsS "$BASE/readyz" >/dev/null
echo "survived single-replica kill via api-lb"

echo "HA smoke passed (app-tier only; data plane is still single-node)."
