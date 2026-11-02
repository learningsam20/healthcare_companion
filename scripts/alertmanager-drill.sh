#!/usr/bin/env bash
# G-25: post a test alert to local Alertmanager and record the HTTP result.
# Records the actual status — does not invent a successful drill.
#
# Compose full profile maps host ${ALERTMANAGER_PORT:-5736} → container 9093.
# Bring the stack up with: docker compose --profile full up -d alertmanager
# (or the full profile). If Alertmanager is unreachable, this script exits
# non-zero and still writes evidence with status failed_or_unreachable.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Prefer explicit URL; else host-mapped Compose port (not container 9093).
if [[ -z "${ALERTMANAGER_URL:-}" ]]; then
  port="${ALERTMANAGER_PORT:-5736}"
  if [[ -f "$ROOT/.env" ]]; then
    env_port="$(grep -E '^[[:space:]]*ALERTMANAGER_PORT=' "$ROOT/.env" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '[:space:]' || true)"
    [[ -n "$env_port" ]] && port="$env_port"
  fi
  URL="http://127.0.0.1:${port}"
else
  URL="${ALERTMANAGER_URL}"
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$ROOT/docs/evidence/alertmanager-drill-$stamp.json"
starts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
body_file="$(mktemp)"
err_file="$(mktemp)"
ready_file="$(mktemp)"
trap 'rm -f "$body_file" "$err_file" "$ready_file"' EXIT

payload="[{\"labels\":{\"alertname\":\"SahyogDrill\",\"severity\":\"info\",\"service\":\"sahyog\"},\"annotations\":{\"summary\":\"G-25 drill\"},\"startsAt\":\"${starts}\"}]"

set +e
ready_code="$(curl -sS -o "$ready_file" -w '%{http_code}' --connect-timeout 2 --max-time 5 \
  "$URL/-/ready" 2>"$err_file")"
ready_rc=$?
set -e

if [[ "$ready_rc" -ne 0 || "$ready_code" != "200" ]]; then
  OUT="$out" URL="$URL" HTTP="" RC="$ready_rc" BODY_FILE="$ready_file" ERR_FILE="$err_file" \
    STAMP="$stamp" READY="$ready_code" python3 - <<'PY'
import json, os
from pathlib import Path
body = Path(os.environ["BODY_FILE"]).read_text(encoding="utf-8", errors="replace")[:500]
err = Path(os.environ["ERR_FILE"]).read_text(encoding="utf-8", errors="replace")[:500]
ready = os.environ.get("READY") or ""
report = {
  "generated_at": os.environ["STAMP"],
  "url": os.environ["URL"] + "/api/v2/alerts",
  "ready_url": os.environ["URL"] + "/-/ready",
  "ready_http_status": int(ready) if ready.isdigit() else None,
  "http_status": None,
  "curl_rc": int(os.environ["RC"]),
  "body_excerpt": body,
  "error": err or "Alertmanager /-/ready not reachable",
  "status": "failed_or_unreachable",
  "note": (
    "Alertmanager not up. Start with: docker compose --profile full up -d alertmanager. "
    "Host port defaults to ALERTMANAGER_PORT=5736 (see docker-compose.yml). "
    "No invented success metrics."
  ),
}
Path(os.environ["OUT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(1)
PY
fi

set +e
http_code="$(curl -sS -o "$body_file" -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' \
  --connect-timeout 2 --max-time 10 \
  --data "$payload" \
  "$URL/api/v2/alerts" 2>"$err_file")"
rc=$?
set -e
OUT="$out" URL="$URL" HTTP="$http_code" RC="$rc" BODY_FILE="$body_file" ERR_FILE="$err_file" STAMP="$stamp" python3 - <<'PY'
import json, os
from pathlib import Path
body = Path(os.environ["BODY_FILE"]).read_text(encoding="utf-8", errors="replace")[:500]
err = Path(os.environ["ERR_FILE"]).read_text(encoding="utf-8", errors="replace")[:500]
http = os.environ.get("HTTP") or ""
report = {
  "generated_at": os.environ["STAMP"],
  "url": os.environ["URL"] + "/api/v2/alerts",
  "http_status": int(http) if http.isdigit() else None,
  "curl_rc": int(os.environ["RC"]),
  "body_excerpt": body,
  "error": err,
  "status": "passed" if http in {"200", "202"} else "failed_or_unreachable",
  "note": "Actual Alertmanager response; not a signed on-call drill.",
}
Path(os.environ["OUT"]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if http in {"200", "202"} else 1)
PY
