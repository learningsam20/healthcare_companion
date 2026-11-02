#!/usr/bin/env bash
# Shared helpers for the Sahyog operator scripts.
#
# Bash 3.2 compatible (the macOS default). Never source .env as shell code: values are
# parsed as data by Python and never evaluated. No secret is printed by these helpers.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'
else
  C_RESET=""
  C_BOLD=""
  C_DIM=""
  C_RED=""
  C_GREEN=""
  C_YELLOW=""
  C_BLUE=""
fi

say() { printf '%s\n' "$*"; }
step() { printf '\n%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok() { printf '%sok%s  %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die() {
  printf '%serror%s %s\n' "$C_RED" "$C_RESET" "$*" >&2
  exit 1
}
dim() { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }

dotenv_or_env() {
  local key="$1" default="${2-}"
  env_value "$key" "$default"
}

require_cmd() {
  local name
  for name in "$@"; do
    command -v "$name" >/dev/null 2>&1 || die "required command not found: $name"
  done
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE; copy .env.example to .env and fill every placeholder"
}

# Read KEY from the process environment first, then .env, then the default.
env_value() {
  local key="$1" default="${2-}"
  python3 - "$ENV_FILE" "$key" "$default" <<'PY'
import os
import sys

path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
values: dict[str, str] = {}
try:
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            else:
                for index, char in enumerate(value):
                    if char == "#" and (index == 0 or value[index - 1] in " \t"):
                        value = value[:index].rstrip()
                        break
            values[name] = value
except FileNotFoundError:
    pass
print(os.environ.get(key, values.get(key, default)))
PY
}

env_bool() {
  local value
  value="$(env_value "$1" "${2:-false}" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1 | true | yes | on) printf '1\n' ;;
    *) printf '0\n' ;;
  esac
}

is_placeholder() {
  local value="$1"
  case "$value" in
    "" | replace-* | *replace-me* | *replace-with* | changeme | change-me | example | \<*\>)
      return 0
      ;;
  esac
  return 1
}

# check_required_keys KEY... never prints values.
check_required_keys() {
  local key value missing=()
  for key in "$@"; do
    value="$(env_value "$key" "")"
    if [[ -z "$value" ]]; then
      missing+=("$key (empty)")
    elif is_placeholder "$value"; then
      missing+=("$key (placeholder)")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    warn "fix these entries in $ENV_FILE:"
    printf '  - %s\n' "${missing[@]}" >&2
    return 1
  fi
}

check_min_length() {
  local key="$1" minimum="$2" value
  value="$(env_value "$key" "")"
  if (( ${#value} < minimum )); then
    warn "$key must be at least $minimum characters"
    return 1
  fi
}

profile_keys() {
  local profile="$1"
  cat <<'EOF'
APP_SECRET_KEY
POSTGRES_PASSWORD
LITELLM_DB_PASSWORD
LANGFUSE_DB_PASSWORD
KEYCLOAK_DB_PASSWORD
LITELLM_MASTER_KEY
MCP_SERVICE_TOKEN
MCP_CONTEXT_SECRET
PII_TOKEN_SECRET
S3_ACCESS_KEY
S3_SECRET_KEY
KEYCLOAK_ADMIN_PASSWORD
KEYCLOAK_ADMIN_CLIENT_SECRET
KEYCLOAK_CLI_CLIENT_SECRET
KEYCLOAK_MCP_CLIENT_SECRET
SEED_DEMO_PASSWORD
EOF
  case "$profile" in
    core | full)
      cat <<'EOF'
LANGFUSE_NEXTAUTH_SECRET
LANGFUSE_SALT
LANGFUSE_ENCRYPTION_KEY
EOF
      ;;
  esac
  if [[ "$profile" == "full" ]]; then
    printf 'GRAFANA_ADMIN_PASSWORD\n'
  fi
}

validate_profile_env() {
  local profile="$1" keys=() key
  while IFS= read -r key; do
    [[ -n "$key" ]] && keys+=("$key")
  done < <(profile_keys "$profile")
  check_required_keys "${keys[@]}" || die "environment is incomplete for profile $profile"
  check_min_length APP_SECRET_KEY 32 || die "APP_SECRET_KEY is too short"
  check_min_length MCP_CONTEXT_SECRET 32 || die "MCP_CONTEXT_SECRET is too short"
  check_min_length PII_TOKEN_SECRET 32 || die "PII_TOKEN_SECRET is too short"
  local seed_password
  seed_password="$(env_value SEED_DEMO_PASSWORD "")"
  if (( ${#seed_password} < 12 )); then
    die "SEED_DEMO_PASSWORD must be at least 12 characters"
  fi
}

# Profiles are cumulative; Compose itself does not inherit them.
set_compose_profile() {
  local profile="$1" melt="${2:-0}" profiles
  case "$profile" in
    minimal) profiles="minimal" ;;
    core) profiles="minimal,core" ;;
    full) profiles="minimal,core,full" ;;
    *) die "unknown profile: $profile (expected minimal, core or full)" ;;
  esac
  if [[ "$melt" == "1" ]]; then
    profiles="$profiles,melt"
  fi
  export COMPOSE_PROFILES="$profiles"
  export APP_PROFILE="$profile"
  export WITH_MELT="$melt"
  if [[ "$profile" == "full" ]]; then
    # Scanning is mandatory when the scanner ships with the profile. An explicit
    # value in .env still wins, so an operator can choose advisory during a drill.
    if [[ -z "${CLAMAV_HOST:-}" ]]; then
      CLAMAV_HOST="$(env_value CLAMAV_HOST "")"
      export CLAMAV_HOST="${CLAMAV_HOST:-clamav}"
    fi
    if [[ -z "${MALWARE_SCAN_MODE:-}" ]]; then
      MALWARE_SCAN_MODE="$(env_value MALWARE_SCAN_MODE "")"
      export MALWARE_SCAN_MODE="${MALWARE_SCAN_MODE:-required}"
    fi
  fi
}

activate_profile_from_env() {
  local profile melt
  profile="$(env_value APP_PROFILE core)"
  melt="${WITH_MELT:-0}"
  set_compose_profile "$profile" "$melt"
}

compose() {
  (cd "$ROOT" && docker compose --env-file "$ENV_FILE" "$@")
}

# Include services from every profile, e.g. to stop a previous full-profile run.
compose_all() {
  compose --profile "*" "$@"
}

compose_run_api() {
  compose run --rm --no-deps -T api "$@"
}

compose_has_service() {
  local service="$1"
  compose config --services 2>/dev/null | grep -qx "$service"
}

compose_container_id() {
  compose ps -q "$1" 2>/dev/null | head -n 1
}

wait_http() {
  local url="$1" label="$2" timeout="${3:-120}" started=$SECONDS
  printf '  waiting for %s' "$label"
  while ! curl -fsS --max-time 5 "$url" >/dev/null 2>&1; do
    if (( SECONDS - started >= timeout )); then
      printf '\n'
      warn "$label did not become ready within ${timeout}s ($url)"
      return 1
    fi
    printf '.'
    sleep 2
  done
  printf ' %sready%s\n' "$C_GREEN" "$C_RESET"
}

wait_compose_healthy() {
  local service="$1" timeout="${2:-180}" started=$SECONDS cid status
  printf '  waiting for %s' "$service"
  while true; do
    cid="$(compose_container_id "$service")"
    if [[ -n "$cid" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      case "$status" in
        healthy | running)
          printf ' %sready%s\n' "$C_GREEN" "$C_RESET"
          return 0
          ;;
      esac
    fi
    if (( SECONDS - started >= timeout )); then
      printf '\n'
      warn "$service did not become healthy within ${timeout}s"
      compose logs --tail=40 --no-color "$service" >&2 2>/dev/null || true
      return 1
    fi
    printf '.'
    sleep 2
  done
}

# TCP check against a published host port (Compose health alone is not enough for --local).
wait_host_http() {
  local url="$1" label="$2" timeout="${3:-90}" started=$SECONDS code
  printf '  waiting for %s at %s' "$label" "$url"
  while true; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || printf '000')"
    if [[ "$code" == "200" || "$code" == "302" ]]; then
      printf ' %sready%s\n' "$C_GREEN" "$C_RESET"
      return 0
    fi
    if (( SECONDS - started >= timeout )); then
      printf '\n'
      die "$label did not return HTTP 200 at ${url} (last=${code}). Try: docker restart sahyog-keycloak-1"
    fi
    printf '.'
    sleep 2
  done
}

wait_host_tcp() {
  local host="$1" port="$2" label="$3" timeout="${4:-60}" started=$SECONDS
  printf '  waiting for %s on %s:%s' "$label" "$host" "$port"
  while ! python3 - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  do
    if (( SECONDS - started >= timeout )); then
      printf '\n'
      die "$label is not reachable at ${host}:${port}. Containers on an internal-only Docker network do not publish ports; recreate postgres/redis on the app+data networks (see docker-compose.yml)."
    fi
    printf '.'
    sleep 1
  done
  printf ' %sready%s\n' "$C_GREEN" "$C_RESET"
}

# Real Keycloak password grant through the local operator client. Never a bypass.
keycloak_token() {
  local username="$1" password="${2:-}" realm client_id client_secret base response token
  realm="$(env_value KEYCLOAK_REALM sahyog)"
  client_id="$(env_value KEYCLOAK_CLI_CLIENT_ID sahyog-cli)"
  client_secret="$(env_value KEYCLOAK_CLI_CLIENT_SECRET "")"
  base="$(env_value KEYCLOAK_PUBLIC_URL http://localhost:5707)"
  [[ -n "$password" ]] || password="$(env_value SEED_DEMO_PASSWORD "")"
  [[ -n "$client_secret" ]] || die "KEYCLOAK_CLI_CLIENT_SECRET is not set"
  response="$(curl -fsS --max-time 15 -X POST \
    "$base/realms/$realm/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode "client_id=$client_id" \
    --data-urlencode "client_secret=$client_secret" \
    --data-urlencode "username=$username" \
    --data-urlencode "password=$password" \
    --data-urlencode 'scope=openid profile email')" || {
    warn "Keycloak login failed for $username"
    return 1
  }
  token="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' <<<"$response")"
  [[ -n "$token" ]] || die "Keycloak returned no access token for $username"
  printf '%s\n' "$token"
}

api_get() {
  local path="$1" token="$2"
  curl -fsS --max-time 20 -H "Authorization: Bearer $token" \
    -H 'Accept: application/json' "${API_BASE_URL%/}${path}"
}

api_post() {
  local path="$1" token="$2" body="${3:-{}}"
  curl -fsS --max-time 20 -X POST -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    --data "$body" "${API_BASE_URL%/}${path}"
}

require_confirmation() {
  local prompt="$1"
  if [[ "${CONFIRM:-0}" == "1" ]]; then
    warn "$prompt"
    return 0
  fi
  if [[ -t 0 ]]; then
    printf '%s\nType "yes" to continue: ' "$prompt"
    local answer
    read -r answer
    [[ "$answer" == "yes" ]] || die "aborted"
    return 0
  fi
  die "refusing a destructive action without --confirm in a non-interactive shell"
}

redact_stream() {
  sed -E \
    -e 's/([Aa]uthorization: *[Bb]earer +)[^ "]+/\1[redacted]/g' \
    -e 's/([Aa]ccess_token|[Rr]efresh_token|[Cc]lient_secret|[Pp]assword|[Ss]ecret|[Tt]oken)=([^& "]+)/\1=[redacted]/g'
}

print_env_summary() {
  local key value state
  say "  configuration ($ENV_FILE):"
  for key in APP_ENV APP_PROFILE POSTGRES_DB KEYCLOAK_REALM S3_BUCKET_DOCUMENTS LITELLM_BASE_URL; do
    state="$(env_value "$key" "")"
    printf '    %-22s %s\n' "$key" "${state:-<default>}"
  done
  for key in OPENROUTER_API_KEY SLACK_BOT_TOKEN SMS_BASE_URL SMTP_HOST; do
    value="$(env_value "$key" "")"
    if [[ -n "$value" ]]; then
      printf '    %-22s %s\n' "$key" "configured"
    else
      printf '    %-22s %s\n' "$key" "unconfigured"
    fi
  done
}

print_urls() {
  local profile="$1" web api kc litellm mailpit s3 langfuse grafana mode="${2:-compose}"
  web="$(env_value APP_BASE_URL http://localhost:5705)"
  api="$(env_value API_BASE_URL http://localhost:5706)"
  kc="$(env_value KEYCLOAK_PUBLIC_URL http://localhost:5707)"
  litellm="http://localhost:$(env_value LITELLM_PORT 5708)"
  mailpit="http://localhost:$(env_value MAILPIT_UI_PORT 5718)"
  s3="http://localhost:$(env_value S3_PORT "$(env_value MINIO_PORT 5719)")"
  langfuse="http://localhost:$(env_value LANGFUSE_PORT 5721)"
  grafana="http://localhost:$(env_value GRAFANA_PORT 5723)"
  if [[ "$mode" == "local" ]]; then
    web="http://localhost:$(env_value VITE_DEV_PORT 5729)"
    api="http://localhost:$(env_value API_PORT 5706)"
  fi
  say ""
  say "  Web            $web"
  say "  API health     $api/healthz"
  say "  API readiness  $api/readyz"
  say "  Keycloak       $kc (realm $(env_value KEYCLOAK_REALM sahyog))"
  say "  LiteLLM        $litellm/health/liveliness"
  say "  Mailpit        $mailpit"
  say "  S3Proxy        $s3 (aws-v4; S3_ACCESS_KEY)"
  if [[ "$profile" == "core" || "$profile" == "full" ]]; then
    say "  Langfuse       $langfuse"
  fi
  if [[ "$profile" == "full" ]]; then
    say "  Grafana        $grafana"
    say "  Prometheus     http://localhost:$(env_value PROMETHEUS_PORT 5722)"
  fi
  if [[ "$mode" == "local" ]]; then
    say ""
    dim "  Mode: local host app (API/UI/agents + ARQ workers). Dependencies stay in Docker."
  fi
  say ""
  dim "  No passwords are printed. Sign in with a seeded Keycloak user."
}

# App-tier Compose services that conflict with host ports when --local is used.
COMPOSE_APP_TIER_SERVICES="api web worker scheduler"

stop_compose_app_tier() {
  # Best-effort: free 5705/5706 so host uvicorn/Vite can bind.
  # shellcheck disable=SC2086
  compose stop $COMPOSE_APP_TIER_SERVICES >/dev/null 2>&1 || true
}

# Load .env into this process for host/--local tools (Compose normally injects these).
# Never evaluates .env as shell; never prints values; never overwrites an already-set var.
export_dotenv_into_environ() {
  local key value
  while IFS= read -r -d '' key && IFS= read -r -d '' value; do
    if printenv "$key" >/dev/null 2>&1; then
      continue
    fi
    printf -v "$key" '%s' "$value"
    export "$key"
  done < <(
    python3 - "$ENV_FILE" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
values: dict[str, str] = {}
try:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            for index, char in enumerate(value):
                if char == "#" and (index == 0 or value[index - 1] in " \t"):
                    value = value[:index].rstrip()
                    break
        values[name] = value
except FileNotFoundError:
    sys.exit(0)
out = sys.stdout.buffer
for name, value in values.items():
    if name in os.environ:
        continue
    out.write(name.encode("utf-8") + b"\0" + value.encode("utf-8") + b"\0")
PY
  )
}

# Rewrite container DNS names in .env to published localhost ports for host processes.
export_host_runtime_env() {
  local postgres_port redis_port keycloak_port litellm_port minio_port
  local mcp_broker_port mcp_pii_port api_port
  export_dotenv_into_environ
  postgres_port="$(env_value POSTGRES_PORT 5724)"
  redis_port="$(env_value REDIS_PORT 5725)"
  keycloak_port="$(env_value KEYCLOAK_PORT 5707)"
  litellm_port="$(env_value LITELLM_PORT 5708)"
  minio_port="$(env_value S3_PORT "$(env_value MINIO_PORT 5719)")"
  mcp_broker_port="$(env_value MCP_BROKER_PORT 5709)"
  mcp_pii_port="$(env_value MCP_PII_PORT 5715)"
  api_port="$(env_value API_PORT 5706)"

  local database_url redis_url
  database_url="$(env_value DATABASE_URL "")"
  database_url="${database_url/@postgres:5432/@localhost:$postgres_port}"
  [[ "$database_url" == *"@localhost:$postgres_port"* ]] ||
    die "DATABASE_URL must use host postgres:5432 in .env so local mode can rewrite it to localhost:$postgres_port"
  redis_url="$(env_value REDIS_URL "redis://redis:6379/0")"
  redis_url="${redis_url/redis:6379/localhost:$redis_port}"

  local web_port mcp_stt_port clamav_port
  web_port="$(env_value VITE_DEV_PORT 5729)"
  mcp_stt_port="$(env_value MCP_STT_PORT 5716)"
  clamav_port="$(env_value CLAMAV_PUBLISH_PORT 5737)"

  export DATABASE_URL="$database_url"
  export REDIS_URL="$redis_url"
  export KEYCLOAK_URL="http://localhost:$keycloak_port"
  export KEYCLOAK_PUBLIC_URL="$(env_value KEYCLOAK_PUBLIC_URL "http://localhost:$keycloak_port")"
  # Admin API is published on the same host port as the public realm URL.
  export KEYCLOAK_ADMIN_URL="http://localhost:$keycloak_port"
  export LITELLM_BASE_URL="http://localhost:$litellm_port"
  export S3_ENDPOINT_URL="http://localhost:$minio_port"
  export S3_PUBLIC_ENDPOINT_URL="http://localhost:$minio_port"
  export MCP_BROKER_URL="http://localhost:$mcp_broker_port"
  # Settings reads PII_SERVICE_URL (not MCP_PII_URL).
  export PII_SERVICE_URL="http://localhost:$mcp_pii_port"
  export MCP_PII_URL="http://localhost:$mcp_pii_port"
  export MCP_STT_URL="http://localhost:$mcp_stt_port"
  export SAHYOG_API_URL="http://127.0.0.1:$api_port"
  export API_BASE_URL="http://localhost:$api_port"
  # Host Ollama — never use Docker DNS from a host-side API process.
  export OLLAMA_BASE_URL="http://127.0.0.1:11434"
  export EMBEDDING_BASE_URL="http://127.0.0.1:11434/v1"
  export DECIDER_LLAMA_URL="http://localhost:$litellm_port"
  export CONFIG_DIR="$ROOT/config"
  # Langfuse ingestion from a host-side API must use the published loopback port —
  # Compose DNS ``langfuse-web`` does not resolve on the Mac host (G-23).
  local langfuse_port
  langfuse_port="$(env_value LANGFUSE_PORT 5721)"
  export LANGFUSE_HOST="http://127.0.0.1:$langfuse_port"
  export LANGFUSE_PUBLIC_URL="$(env_value LANGFUSE_PUBLIC_URL "http://localhost:$langfuse_port")"
  # Host processes should not push OTLP into the collector's Docker DNS name by default.
  export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-}"
  # Empty base → browser calls same-origin /api (Vite proxy). Avoids CORS when
  # the page is opened as 127.0.0.1 while VITE_API_BASE_URL pointed at localhost.
  export VITE_API_BASE_URL=""
  export VITE_API_PROXY="http://127.0.0.1:$api_port"
  export VITE_DEV_PORT="$web_port"
  export VITE_OIDC_AUTHORITY="http://localhost:$keycloak_port/realms/$(env_value KEYCLOAK_REALM sahyog)"
  export VITE_OIDC_REDIRECT_URI="http://localhost:${web_port}/auth/callback"
  export VITE_OIDC_POST_LOGOUT_REDIRECT_URI="http://localhost:${web_port}/"
  # Allow both hostnames Vite may print (localhost vs 127.0.0.1).
  export CORS_ORIGINS="http://localhost:5705,http://127.0.0.1:5705,http://localhost:${web_port},http://127.0.0.1:${web_port}"
  # ClamAV is optional on host; publish port when full profile started it.
  if [[ "$(env_value CLAMAV_HOST "")" == "clamav" || "$(env_value MALWARE_SCAN_MODE advisory)" == "required" ]]; then
    export CLAMAV_HOST="127.0.0.1"
    export CLAMAV_PORT="$clamav_port"
  fi
  local mem0_port
  mem0_port="$(env_value MEM0_PORT 5730)"
  if [[ -n "$(env_value MEM0_URL "")" ]]; then
    export MEM0_URL="http://localhost:$mem0_port"
  fi

  # Fail fast if published ports are missing (internal-only network attachment).
  step "Checking host-published dependency ports"
  wait_host_tcp 127.0.0.1 "$postgres_port" "Postgres" 45
  wait_host_tcp 127.0.0.1 "$redis_port" "Redis" 45
  wait_host_tcp 127.0.0.1 "$keycloak_port" "Keycloak" 45
  # Docker can report Keycloak healthy on :9000 while the published :8080 proxy
  # still returns empty replies (DB pool flap). Require a real HTTP body on the
  # host port before realm sync.
  wait_host_http "http://127.0.0.1:${keycloak_port}/realms/sahyog" "Keycloak HTTP" 90
  wait_host_tcp 127.0.0.1 "$minio_port" "S3Proxy" 45
}

list_local_infra_services() {
  # stdout: space-separated Compose service names for dependency containers.
  local profile="$1"
  local services="postgres redis s3proxy keycloak mailpit litellm mcp-broker mcp-scheduling mcp-records mcp-clinical mcp-platform mcp-decider mcp-pii"
  if [[ "$profile" == "core" || "$profile" == "full" ]]; then
    services="$services mcp-stt langfuse-web langfuse-worker otel-collector"
  fi
  if [[ "$profile" == "full" ]]; then
    services="$services prometheus alertmanager grafana clamav"
  fi
  if [[ "${WITH_MELT:-0}" == "1" ]]; then
    services="$services clickhouse"
  fi
  printf '%s\n' "$services"
}

# Resolve after the helper functions exist; sourcing this file never evaluates .env.
API_BASE_URL="${API_BASE_URL:-$(dotenv_or_env API_BASE_URL http://localhost:5706)}"
