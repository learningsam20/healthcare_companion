#!/usr/bin/env bash
# Lint, type-check and dependency-boundary checks.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/lint.sh [--fix]

  --fix   Apply safe Ruff fixes and formatting before checking
EOF
}

FIX=0
while (( $# > 0 )); do
  case "$1" in
    --fix) FIX=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_cmd uv npm
cd "$ROOT"

if (( FIX == 1 )); then
  step "Applying Ruff fixes"
  uv run ruff check --fix .
  uv run ruff format .
fi

step "Ruff"
uv run ruff check .
uv run ruff format --check .

step "mypy (strict)"
uv run mypy apps/api/app packages/py-common/sahyog_common scripts/validate_config.py \
  scripts/validate_data.py scripts/flags_report.py

step "Import boundaries"
uv run lint-imports

step "Web typecheck"
if [[ -d apps/web/node_modules ]]; then
  npm --prefix apps/web run typecheck
else
  die "apps/web/node_modules is missing; run npm --prefix apps/web install"
fi

if command -v semgrep >/dev/null 2>&1; then
  step "Semgrep"
  semgrep --config auto --error --quiet --exclude node_modules --exclude .venv .
else
  dim "  semgrep not installed; security scan skipped (recorded as a local gap)"
fi

ok "lint and type checks passed"
