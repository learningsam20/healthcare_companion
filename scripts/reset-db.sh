#!/usr/bin/env bash
# Destructive local rebuild: drop the application schema, migrate and seed.
#
# Object storage is untouched unless --objects is passed and confirmed separately.
# Keycloak and its users are never touched by this script.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/reset-db.sh [--confirm] [--objects] [--no-seed]

  --confirm   Required in a non-interactive shell
  --objects   Also delete every object in the six private buckets (separate confirmation)
  --no-seed   Rebuild the schema but do not load the synthetic demo dataset

This is destructive. It drops the public schema of the application database only.
EOF
}

OBJECTS=0
SEED=1
while (( $# > 0 )); do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --objects) OBJECTS=1; shift ;;
    --no-seed) SEED=0; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker curl python3
activate_profile_from_env
validate_profile_env "$APP_PROFILE"

POSTGRES_USER_VALUE="$(env_value POSTGRES_USER sahyog)"
POSTGRES_DB_VALUE="$(env_value POSTGRES_DB sahyog)"
[[ "$POSTGRES_USER_VALUE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] ||
  die "POSTGRES_USER must be a simple SQL identifier"
[[ "$POSTGRES_DB_VALUE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] ||
  die "POSTGRES_DB must be a simple SQL identifier"

wait_compose_healthy postgres 120 >/dev/null ||
  die "Postgres is not healthy; run scripts/start.sh first"

require_confirmation "Drop every table in database '$POSTGRES_DB_VALUE' and rebuild it from migrations?"

if (( OBJECTS == 1 )); then
  require_confirmation "Also delete EVERY object in the six private buckets, including eval and backup objects?"
fi

step "Dropping and recreating schema public"
compose exec -T postgres psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER_VALUE" --dbname "$POSTGRES_DB_VALUE" \
  -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' >/dev/null
ok "schema recreated"

step "Running migrations"
compose run --rm --no-deps -T -w /app/apps/api api alembic upgrade head ||
  die "migrations failed after the reset"
ok "schema is at head"

if (( OBJECTS == 1 )); then
  step "Deleting objects from every bucket"
  compose run --rm --no-deps --entrypoint /bin/bash s3-init -c '
    set -euo pipefail
    export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
    export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
    export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
    export AWS_EC2_METADATA_DISABLED=true
    ENDPOINT="${S3_ENDPOINT_URL:-http://s3proxy:80}"
    for bucket in "$S3_BUCKET_DOCUMENTS" "$S3_BUCKET_AUDIO" "$S3_BUCKET_EXPORTS" \
      "$S3_BUCKET_ANCHORS" "$S3_BUCKET_EVAL" "$S3_BUCKET_BACKUPS"; do
      aws --endpoint-url "$ENDPOINT" s3 rm "s3://$bucket" --recursive >/dev/null 2>&1 || true
    done
  ' || die "object deletion failed"
  ok "private buckets are empty"
fi

if (( SEED == 1 )); then
  step "Seeding the synthetic sample dataset"
  compose_run_api python scripts/seed_demo.py >/dev/null
  compose_run_api python scripts/keycloak_admin.py sync-demo-links >/dev/null
  ok "synthetic sample data loaded and linked to Keycloak subjects"
fi

ok "database reset complete; Keycloak users and realm were not changed"
