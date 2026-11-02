#!/usr/bin/env bash
# Start a Sahyog profile with explicit validation, migrations and realm sync.
#
# Profiles are cumulative: minimal, core (minimal+core), full (minimal+core+full).
# Use --with-melt for the optional ClickHouse demonstration.
# Use --local to run API / UI / agents / ARQ workers on the host while dependencies
# stay in Docker (faster edit–reload debugging).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/start.sh [options]

  --profile minimal|core|full   Target profile (default: APP_PROFILE in .env, or minimal)
  --local                       Host the app UI, API (agents in-process) and ARQ workers
                                on the machine; keep Postgres/Keycloak/Redis/MinIO/LiteLLM/MCP
                                (and profile extras) in Docker
  --with-melt                   Add the optional melt/ClickHouse profile
  --no-build                    Reuse existing images (ignored with --local)
  --seed                        Seed Keycloak users + synthetic sample data after migration
  --no-workers                  With --local: skip host ARQ worker/scheduler

Docker mode (default):
  ./scripts/start.sh --profile minimal

Local host-app mode (deps in Docker):
  ./scripts/start.sh --profile minimal --local
  # equivalent shortcut after deps are up:
  ./scripts/dev.sh --profile minimal

The script never bypasses readiness and never prints credentials.
EOF
}

PROFILE="$(env_value APP_PROFILE minimal)"
WITH_MELT_FLAG=0
BUILD=1
SEED=0
LOCAL_APP=0
LOCAL_WORKERS=1

while (( $# > 0 )); do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || die "--profile requires a value"
      PROFILE="$2"
      shift 2
      ;;
    --profile=*)
      PROFILE="${1#*=}"
      shift
      ;;
    --local)
      LOCAL_APP=1
      shift
      ;;
    --with-melt)
      WITH_MELT_FLAG=1
      shift
      ;;
    --no-build)
      BUILD=0
      shift
      ;;
    --seed)
      SEED=1
      shift
      ;;
    --no-workers)
      LOCAL_WORKERS=0
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1 (try --help)"
      ;;
  esac
done

case "$PROFILE" in
  minimal | core | full) ;;
  *) die "unknown profile: $PROFILE (expected minimal, core or full)" ;;
esac

require_env_file
require_cmd docker curl python3
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
docker info >/dev/null 2>&1 || die "Docker daemon is not reachable"

set_compose_profile "$PROFILE" "$WITH_MELT_FLAG"
validate_profile_env "$PROFILE"

step "Validating configuration"
for file in config/app.yaml config/models.yaml config/features.yaml config/metrics.yaml \
  config/finops_model.yaml config/notifications.yaml config/red_flags.yaml; do
  [[ -f "$ROOT/$file" ]] || die "missing configuration file: $file"
done
compose config -q || die "Compose configuration is invalid; fix .env before starting"

if (( LOCAL_APP == 1 )); then
  require_cmd uv npm
  [[ -d "$ROOT/apps/web/node_modules" ]] ||
    die "apps/web/node_modules is missing; run: npm --prefix apps/web install"
  if [[ "$(env_bool HA_MODE false)" == "1" || "$(env_bool CHECKPOINTER_REQUIRED false)" == "1" ]]; then
    uv run python -c "import psycopg; assert psycopg.pq.__impl__ == 'binary'" >/dev/null 2>&1 ||
      die "HA_MODE/CHECKPOINTER_REQUIRED needs psycopg[binary] on the host; run: uv sync --all-packages"
  fi

  step "Starting dependency containers only ($PROFILE, local host-app mode)"
  # shellcheck disable=SC2046
  compose up -d $(list_local_infra_services "$PROFILE")
  wait_compose_healthy postgres 120
  wait_compose_healthy redis 60
  wait_compose_healthy s3proxy 120
  wait_compose_healthy keycloak 240
  ok "data dependencies are healthy"

  step "Bootstrapping object storage buckets"
  compose run --rm --no-deps -T s3-init || die "bucket bootstrap failed"
  ok "buckets are present"

  stop_compose_app_tier
  export_host_runtime_env

  step "Running database migrations (host)"
  (cd "$ROOT/apps/api" && uv run alembic upgrade head) || die "migrations failed"
  ok "migrations are at head"

  step "Synchronising the Keycloak realm"
  (
    cd "$ROOT"
    uv run python scripts/keycloak_admin.py sync
  ) >/tmp/sahyog-keycloak-sync.json || die "Keycloak realm sync failed"
  python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/sahyog-keycloak-sync.json").read_text())
print(json.dumps({k: payload.get(k) for k in ("realm", "clients", "roles") if k in payload}, indent=2))
PY
  rm -f /tmp/sahyog-keycloak-sync.json

  if (( SEED == 1 )); then
    step "Seeding demo users and sample data"
    "$ROOT/scripts/seed-users.sh"
    "$ROOT/scripts/load-data.sh" --sample
  fi

  printf '\n%sSahyog dependencies are up; starting host app tier (%s%s)%s\n' \
    "$C_GREEN" "$PROFILE" \
    "$([[ "$WITH_MELT_FLAG" == "1" ]] && printf ', melt')" "$C_RESET"
  print_urls "$PROFILE" local
  if (( SEED == 1 )); then
    say ""
    dim "  Demo users were seeded; passwords come from SEED_DEMO_PASSWORD and are never printed."
  else
    say ""
    dim "  No users were seeded. Run ./scripts/seed-users.sh, then ./scripts/load-data.sh --sample."
  fi

  # Hand off to the long-running host processes (replaces this shell).
  local_args=(--profile "$PROFILE" --no-infra --local)
  if (( WITH_MELT_FLAG == 1 )); then
    local_args+=(--with-melt)
  fi
  if (( LOCAL_WORKERS == 0 )); then
    local_args+=(--no-workers)
  fi
  exec "$ROOT/scripts/dev.sh" "${local_args[@]}"
fi

# -------------------- full Compose mode (API/UI/workers in Docker) --------------------

if (( BUILD == 1 )); then
  step "Building images (sahyog-api:local and web)"
  compose build
else
  docker image inspect sahyog-api:local >/dev/null 2>&1 ||
    die "sahyog-api:local is missing; run without --no-build at least once"
fi

step "Validating application configuration"
compose_run_api python scripts/validate_config.py ||
  die "application configuration is invalid; see the errors above"

step "Starting data dependencies"
compose up -d postgres redis s3proxy keycloak mailpit
wait_compose_healthy postgres 120
wait_compose_healthy redis 60
wait_compose_healthy s3proxy 120
wait_compose_healthy keycloak 240
ok "data dependencies are healthy"

step "Bootstrapping object storage buckets"
compose run --rm --no-deps -T s3-init || die "bucket bootstrap failed"
ok "buckets are present"

step "Running database migrations"
compose run --rm --no-deps -T -w /app/apps/api api alembic upgrade head ||
  die "migrations failed"
ok "migrations are at head"

step "Synchronising the Keycloak realm"
compose_run_api python scripts/keycloak_admin.py sync >/tmp/sahyog-keycloak-sync.json ||
  die "Keycloak realm sync failed"
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/sahyog-keycloak-sync.json").read_text())
print(json.dumps({k: payload.get(k) for k in ("realm", "clients", "roles") if k in payload}, indent=2))
PY
rm -f /tmp/sahyog-keycloak-sync.json

if (( SEED == 1 )); then
  step "Seeding demo users and sample data"
  "$ROOT/scripts/seed-users.sh"
  "$ROOT/scripts/load-data.sh" --sample
fi

step "Starting application services"
trap 'warn "start failed; inspect with ./scripts/status.sh and ./scripts/logs.sh --no-follow"' ERR
compose up -d

step "Waiting for readiness"
wait_compose_healthy api 180
wait_http "${API_BASE_URL%/}/healthz" "API liveness" 120
wait_http "${API_BASE_URL%/}/readyz" "API readiness" 180
wait_compose_healthy web 120
if [[ "$PROFILE" == "core" || "$PROFILE" == "full" ]]; then
  wait_compose_healthy langfuse-web 180
fi
if [[ "$PROFILE" == "full" ]]; then
  wait_compose_healthy grafana 120
fi
trap - ERR

printf '\n%sSahyog is running (%s%s)%s\n' "$C_GREEN" "$PROFILE" \
  "$([[ "$WITH_MELT_FLAG" == "1" ]] && printf ', melt')" "$C_RESET"
print_urls "$PROFILE" compose
if (( SEED == 1 )); then
  say ""
  dim "  Demo users were seeded; passwords come from SEED_DEMO_PASSWORD and are never printed."
else
  say ""
  dim "  No users were seeded. Run ./scripts/seed-users.sh, then ./scripts/load-data.sh --sample."
fi
