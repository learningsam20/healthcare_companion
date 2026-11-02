#!/usr/bin/env bash
# Run unit, scope, PII, contract and i18n checks.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/test.sh [--postgres] [--pii] [--authz] [--contracts] [--i18n] [--e2e]

  (none)       Run the whole pytest suite
  --postgres   Run tests marked integration (requires a running stack)
  --pii        Run PII, red-flag and provenance tests
  --authz      Run signed-context, scope and broker authorization tests
  --contracts  Validate the OpenAPI contract and server-grid parameters
  --i18n       Compare en-IN/hi-IN/mr-IN key coverage and placeholders
  --e2e        Playwright/axe browser suite against the running Compose stack

Options can be combined. The browser suite signs in through real Keycloak and
reads storage state under apps/web/e2e/.auth; keep the stack running.
EOF
}

POSTGRES=0
PII=0
AUTHZ=0
CONTRACTS=0
I18N=0
E2E=0
while (( $# > 0 )); do
  case "$1" in
    --postgres) POSTGRES=1; shift ;;
    --pii) PII=1; shift ;;
    --authz) AUTHZ=1; shift ;;
    --contracts) CONTRACTS=1; shift ;;
    --i18n) I18N=1; shift ;;
    --e2e) E2E=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_cmd uv python3
cd "$ROOT"

if (( E2E == 1 )); then
  step "Browser end-to-end (Playwright/axe)"
  require_cmd npm
  [[ -d "$ROOT/apps/web/node_modules" ]] || die "apps/web dependencies are missing; run 'npm ci' in apps/web"
  set +e
  (
    cd "$ROOT/apps/web"
    PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://localhost:5705}" npm run test:e2e
  )
  e2e_status=$?
  set -e
  # G-36: refresh docs/evidence/wcag_report.md from this run's axe scans (never claims AA).
  uv run python "$ROOT/scripts/wcag_report.py" || warn "wcag_report.py failed"
  (( e2e_status == 0 )) || exit "$e2e_status"
fi

if (( POSTGRES == 1 )); then
  step "Integration tests (Postgres)"
  require_cmd docker
  docker image inspect sahyog-api:local >/dev/null 2>&1 ||
    die "sahyog-api:local is missing; start the stack with ./scripts/start.sh --profile core"
  docker network inspect sahyog_data >/dev/null 2>&1 ||
    die "sahyog_data network is missing; start the Compose stack first"
  docker run --rm --network sahyog_data -v "$ROOT:/src:ro" -w /src \
    -e HOME=/tmp \
    -e DEEPEVAL_TELEMETRY_OPT_OUT=1 \
    -e DEEPEVAL_CACHE_FOLDER=/tmp/deepeval \
    -e POSTGRES_HOST=postgres \
    -e POSTGRES_PORT=5432 \
    -e PYTHONDONTWRITEBYTECODE=1 \
    sahyog-api:local sh -lc \
    '/opt/venv/bin/pytest /src -m integration -q -p no:cacheprovider -c /src/pyproject.toml --rootdir=/src'
fi

if (( PII == 1 )); then
  step "PII, red-flag and provenance tests"
  uv run pytest packages/py-common/tests/test_red_flags.py \
    packages/py-common/tests/test_provenance.py \
    services/mcp-clinical/tests/test_clinical_and_pii.py
fi

if (( AUTHZ == 1 )); then
  step "Signed context, scope and broker tests"
  uv run pytest packages/py-common/tests/test_context.py \
    packages/py-common/tests/test_provenance.py \
    services/mcp-broker/tests/test_broker.py
fi

if (( CONTRACTS == 1 )); then
  step "OpenAPI contract"
  uv run python scripts/contract_check.py
fi

if (( I18N == 1 )); then
  step "Locale coverage"
  uv run python scripts/i18n_check.py
fi

if (( POSTGRES == 0 && PII == 0 && AUTHZ == 0 && CONTRACTS == 0 && I18N == 0 && E2E == 0 )); then
  step "Full pytest suite"
  uv run pytest
fi

ok "requested checks passed"
