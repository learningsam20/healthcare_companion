#!/usr/bin/env bash
# Container and endpoint summary. Read-only; safe to run at any time.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

JSON=0
while (( $# > 0 )); do
  case "$1" in
    --json) JSON=1; shift ;;
    -h | --help)
      say "Usage: scripts/status.sh [--json]"
      exit 0
      ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker curl python3
activate_profile_from_env

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

compose_all ps --format json >"$tmpdir/services.json" 2>/dev/null || true

probe() {
  local name="$1" url="$2" result code time
  result="$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}\t%{time_total}' "$url" 2>/dev/null || true)"
  code="${result%%$'\t'*}"
  time="${result#*$'\t'}"
  [[ -n "$code" ]] || code="000"
  [[ "$time" != "$result" ]] || time="0"
  printf '%s\t%s\t%s\t%s\n' "$name" "$url" "$code" "$time" >>"$tmpdir/probes.tsv"
}

API_URL="${API_BASE_URL%/}"
WEB_URL="$(env_value APP_BASE_URL http://localhost:5705)"
KEYCLOAK_BASE="$(env_value KEYCLOAK_PUBLIC_URL http://localhost:5707)"
REALM="$(env_value KEYCLOAK_REALM sahyog)"
: >"$tmpdir/probes.tsv"
probe "web" "$WEB_URL/healthz"
probe "api_liveness" "$API_URL/healthz"
probe "api_readiness" "$API_URL/readyz"
probe "keycloak" "$KEYCLOAK_BASE/realms/$REALM"
probe "litellm" "http://localhost:$(env_value LITELLM_PORT 5708)/health/liveliness"
probe "mcp_broker" "http://localhost:$(env_value MCP_BROKER_PORT 5709)/healthz"
probe "mcp_pii" "http://localhost:$(env_value MCP_PII_PORT 5715)/healthz"
# S3Proxy aws-v4: unauthenticated GET returns 403 when auth is enforced (healthy).
probe "s3proxy" "http://localhost:$(env_value S3_PORT "$(env_value MINIO_PORT 5719)")/"
probe "mailpit" "http://localhost:$(env_value MAILPIT_UI_PORT 5718)/api/v1/info"
if [[ "$APP_PROFILE" == "core" || "$APP_PROFILE" == "full" ]]; then
  probe "langfuse" "http://localhost:$(env_value LANGFUSE_PORT 5721)/api/public/health"
fi
if [[ "$APP_PROFILE" == "full" ]]; then
  probe "prometheus" "http://localhost:$(env_value PROMETHEUS_PORT 5722)/-/ready"
  probe "grafana" "http://localhost:$(env_value GRAFANA_PORT 5723)/api/health"
fi

curl -fsS --max-time 5 "$API_URL/api/v1/meta" >"$tmpdir/meta.json" 2>/dev/null || printf '{}\n' >"$tmpdir/meta.json"

python3 - "$tmpdir" "$APP_PROFILE" "$JSON" <<'PY'
import json
import sys
from pathlib import Path

directory = Path(sys.argv[1])
profile = sys.argv[2]
as_json = sys.argv[3] == "1"

raw = (directory / "services.json").read_text(encoding="utf-8").strip()
services: list[dict] = []
if raw:
    try:
        parsed = json.loads(raw)
        services = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        services = [json.loads(line) for line in raw.splitlines() if line.strip()]

rows = []
for item in services:
    rows.append(
        {
            "service": item.get("Service") or item.get("service") or "",
            "name": item.get("Name") or item.get("name") or "",
            "state": item.get("State") or item.get("state") or "",
            "health": item.get("Health") or item.get("health") or "",
            "status": item.get("Status") or item.get("status") or "",
        }
    )
rows.sort(key=lambda row: row["service"] or row["name"])

probes = []
for line in (directory / "probes.tsv").read_text(encoding="utf-8").splitlines():
    name, url, code, elapsed = line.split("\t")
    http = int(code)
    # S3Proxy with aws-v4 returns 403 to unauthenticated probes when healthy.
    ok = 200 <= http < 400 or (name == "s3proxy" and http == 403)
    probes.append(
        {
            "name": name,
            "url": url,
            "http": http,
            "ok": ok,
            "latency_ms": round(float(elapsed) * 1000, 1),
        }
    )

try:
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
except json.JSONDecodeError:
    meta = {}

payload = {
    "profile": profile,
    "services": rows,
    "endpoints": probes,
    "meta": {
        "version": meta.get("version"),
        "profile": meta.get("profile"),
        "config_hash": meta.get("config_hash"),
    },
}

if as_json:
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0)

print(f"\nProfile: {profile}")
print(f"{'SERVICE':<24} {'STATE':<12} {'HEALTH':<10} STATUS")
print("-" * 78)
if not rows:
    print("(no containers)")
for row in rows:
    print(
        f"{row['service'] or row['name']:<24} {row['state']:<12} "
        f"{(row['health'] or '-'):<10} {row['status']}"
    )
print(f"\n{'ENDPOINT':<18} {'HTTP':<6} {'MS':<8} URL")
print("-" * 78)
for probe in probes:
    marker = "ok" if probe["ok"] else "DOWN"
    print(
        f"{probe['name']:<18} {probe['http']:<6} {probe['latency_ms']:<8} "
        f"{probe['url']}  [{marker}]"
    )
if meta.get("version"):
    print(f"\nAPI version {meta.get('version')}; config {meta.get('config_hash')}")
PY
