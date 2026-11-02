#!/usr/bin/env bash
# Apply Alembic migrations inside the API image. Explicit and idempotent.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/migrate.sh [--revision REV]

  --revision REV  Target revision (default: head). Downgrades require an explicit revision.
EOF
}

REVISION="head"
while (( $# > 0 )); do
  case "$1" in
    --revision)
      [[ $# -ge 2 ]] || die "--revision requires a value"
      REVISION="$2"
      shift 2
      ;;
    --revision=*) REVISION="${1#*=}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ "$REVISION" =~ ^[A-Za-z0-9_+.-]+$ ]] || die "invalid revision: $REVISION"
require_env_file
require_cmd docker
activate_profile_from_env
validate_profile_env "$APP_PROFILE"

step "Applying migrations to $REVISION"
compose run --rm --no-deps -T -w /app/apps/api api alembic upgrade "$REVISION"
ok "database schema is at $REVISION"
