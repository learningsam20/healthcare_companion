#!/usr/bin/env bash
# Load seed/sample or inventory/download actual public sources (FR-DATA).
#
# --sample          Seed/demo only (FR-DATA-12). Never claimed as the public estate.
# --download/--source  Actual Kaggle files via scripts/load_public_sources.py.
#                      Refuses without credentials; never invents row counts.
# Contracts: config/data_sources.yaml, docs/data-contracts/, docs/data-estate-variance.md

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/load-data.sh --sample [--load-test N]
  scripts/load-data.sh --validate
  scripts/load-data.sh --download [--source NAME|all]
  scripts/load-data.sh --source NAME [--source NAME ...]

  --sample       Load the idempotent seed/demo dataset (synthetic seed only)
  --load-test N  Also create N load-test patients (0-100)
  --validate     Run aggregate-only integrity checks and write docs/evidence/
  --source NAME  Inventory (and optionally download) a public source id
  --download     Download public sources via Kaggle (requires operator credentials)

Public sources are never substituted with seed rows. See docs/gaps.md G-35.
EOF
}

SAMPLE=0
VALIDATE=0
DOWNLOAD=0
LOAD_TEST=0
SOURCES=()

while (( $# > 0 )); do
  case "$1" in
    --sample) SAMPLE=1; shift ;;
    --validate) VALIDATE=1; shift ;;
    --download) DOWNLOAD=1; shift ;;
    --load-test)
      [[ $# -ge 2 ]] || die "--load-test requires a number"
      LOAD_TEST="$2"
      shift 2
      ;;
    --load-test=*) LOAD_TEST="${1#*=}"; shift ;;
    --source)
      [[ $# -ge 2 ]] || die "--source requires a name"
      SOURCES+=("$2")
      shift 2
      ;;
    --source=*) SOURCES+=("${1#*=}"); shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

(( SAMPLE == 1 || VALIDATE == 1 || DOWNLOAD == 1 || ${#SOURCES[@]} > 0 )) || {
  usage >&2
  exit 2
}

[[ "$LOAD_TEST" =~ ^[0-9]+$ ]] || die "--load-test must be an integer"
(( LOAD_TEST <= 100 )) || die "--load-test must be 100 or fewer"

if (( DOWNLOAD == 1 || ${#SOURCES[@]} > 0 )); then
  step "Public-source inventory (actual files only)"
  require_cmd python3
  args=()
  (( DOWNLOAD == 1 )) && args+=(--download)
  if (( ${#SOURCES[@]} == 0 )); then
    args+=(--source all)
  else
    for s in "${SOURCES[@]}"; do
      args+=(--source "$s")
    done
  fi
  python3 "$ROOT/scripts/load_public_sources.py" "${args[@]}"
  ok "public-source inventory written under docs/evidence/"
fi

if (( SAMPLE == 1 || VALIDATE == 1 )); then
  require_env_file
  require_cmd docker curl python3
  activate_profile_from_env
  validate_profile_env "$APP_PROFILE"
fi

if (( SAMPLE == 1 )); then
  step "Loading the seed/sample dataset (not G2 public estate)"
  compose_run_api python scripts/seed_demo.py --load-test "$LOAD_TEST" >/dev/null
  compose_run_api python scripts/keycloak_admin.py sync-demo-links >/dev/null
  ok "seed/sample loaded (idempotent; fixed IDs, re-linked to Keycloak subjects)"
fi

if (( VALIDATE == 1 )); then
  step "Validating data integrity (aggregate-only)"
  mkdir -p "$ROOT/docs/evidence"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  report_file="$ROOT/docs/evidence/data-quality-$stamp.json"
  set +e
  report="$(compose_run_api python scripts/validate_data.py)"
  status=$?
  set -e
  printf '%s\n' "$report" >"$report_file"
  printf '%s\n' "$report"
  if (( status != 0 )); then
    die "data validation failed; see $report_file"
  fi
  ok "report written to ${report_file#"$ROOT/"}"
fi
