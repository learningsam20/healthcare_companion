#!/usr/bin/env bash
# Host-run app tier for fast debug: Docker keeps dependencies; API/UI/workers run on the host.
#
# LangGraph agents execute inside the API process. ARQ worker + scheduler handle async jobs.
# Container DNS names from .env are rewritten to published 57xx localhost ports.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/dev.sh [options]

  --profile minimal|core|full   Infrastructure profile (default: APP_PROFILE, or minimal)
  --local                       Alias documenting host-app mode (same as default behaviour)
  --no-infra                    Use an already-running dependency stack; do not start containers
  --no-api                      Do not run the host API (Compose API may already own :5706)
  --no-web                      Do not run Vite
  --workers / --no-workers      Run (default) or skip host ARQ worker + scheduler
  --with-melt                   Include ClickHouse when starting infra

Host URLs (defaults):
  API      http://localhost:5706   (uvicorn --reload; agents in-process)
  Vite UI  http://localhost:5729   (HMR; proxies /api → API)
  Worker   arq app.worker.WorkerSettings
  Scheduler arq app.scheduler.WorkerSettings

Dependencies (Postgres, Keycloak, Redis, MinIO, LiteLLM, MCP, …) stay in Docker.
EOF
}

PROFILE="$(env_value APP_PROFILE minimal)"
START_INFRA=1
RUN_API=1
RUN_WEB=1
RUN_WORKERS=1
WITH_MELT_FLAG="${WITH_MELT:-0}"

while (( $# > 0 )); do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --profile=*) PROFILE="${1#*=}"; shift ;;
    --local) shift ;; # explicit no-op flag for discoverability / start.sh parity
    --no-infra) START_INFRA=0; shift ;;
    --no-api) RUN_API=0; shift ;;
    --no-web) RUN_WEB=0; shift ;;
    --workers) RUN_WORKERS=1; shift ;;
    --no-workers) RUN_WORKERS=0; shift ;;
    --with-melt) WITH_MELT_FLAG=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

case "$PROFILE" in
  minimal | core | full) ;;
  *) die "--profile must be minimal, core or full" ;;
esac

require_env_file
require_cmd uv npm docker python3
set_compose_profile "$PROFILE" "$WITH_MELT_FLAG"
validate_profile_env "$PROFILE"

API_PORT="$(env_value API_PORT 5706)"
WEB_PORT="$(env_value VITE_DEV_PORT 5729)"

if (( START_INFRA == 1 )); then
  step "Starting dependency containers ($PROFILE) — app tier stays on the host"
  # shellcheck disable=SC2046
  compose up -d $(list_local_infra_services "$PROFILE")
  wait_compose_healthy postgres 120
  wait_compose_healthy redis 60
  wait_compose_healthy s3proxy 120
  wait_compose_healthy keycloak 240
  ok "infrastructure is healthy"
fi

step "Stopping Compose app-tier services that would bind host ports"
stop_compose_app_tier
ok "api/web/worker/scheduler containers stopped (if they were running)"

export_host_runtime_env

step "Applying migrations on the host"
(cd "$ROOT/apps/api" && uv run alembic upgrade head >/dev/null)
ok "schema is at head"

api_pid=""
web_pid=""
worker_pid=""
scheduler_pid=""
cleanup() {
  local pid
  for pid in "$api_pid" "$web_pid" "$worker_pid" "$scheduler_pid"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if (( RUN_API == 1 )); then
  step "Starting API on http://localhost:$API_PORT (reload; agents in-process)"
  (
    cd "$ROOT"
    exec uv run uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT" \
      --app-dir apps/api
  ) &
  api_pid=$!
fi

if (( RUN_WORKERS == 1 )); then
  step "Starting ARQ worker + scheduler on the host"
  (
    cd "$ROOT/apps/api"
    exec uv run arq app.worker.WorkerSettings
  ) &
  worker_pid=$!
  (
    cd "$ROOT/apps/api"
    # Safe on minimal: jobs that need core services fail visibly in job_runs.
    exec uv run arq app.scheduler.WorkerSettings
  ) &
  scheduler_pid=$!
fi

if (( RUN_WEB == 1 )); then
  [[ -d "$ROOT/apps/web/node_modules" ]] ||
    die "apps/web/node_modules is missing; run: npm --prefix apps/web install"
  step "Starting Vite on http://localhost:$WEB_PORT (HMR)"
  (
    cd "$ROOT/apps/web"
    # Bind localhost so the printed URL matches OIDC redirect URIs (not 127.0.0.1).
    exec npm run dev -- --port "$WEB_PORT" --host localhost
  ) &
  web_pid=$!
fi

if [[ -z "$api_pid" && -z "$web_pid" && -z "$worker_pid" && -z "$scheduler_pid" ]]; then
  ok "infrastructure is running; nothing was started on the host"
  exit 0
fi

say ""
print_urls "$PROFILE" local
dim "  Open http://localhost:$WEB_PORT (not 127.0.0.1) so OIDC redirects match."
dim "  Ctrl-C stops host processes; dependency containers keep running (./scripts/stop.sh)."

while true; do
  if [[ -n "$api_pid" ]] && ! kill -0 "$api_pid" 2>/dev/null; then
    die "the API process exited"
  fi
  if [[ -n "$web_pid" ]] && ! kill -0 "$web_pid" 2>/dev/null; then
    die "the Vite process exited"
  fi
  if [[ -n "$worker_pid" ]] && ! kill -0 "$worker_pid" 2>/dev/null; then
    die "the worker process exited"
  fi
  if [[ -n "$scheduler_pid" ]] && ! kill -0 "$scheduler_pid" 2>/dev/null; then
    die "the scheduler process exited"
  fi
  sleep 2
done
