#!/usr/bin/env bash
# Restore a Sahyog backup into an empty environment.
#
# Refuses to overwrite application data or objects that already exist. Restores Postgres,
# telemetry databases, object buckets and the Keycloak realm, reruns migrations, verifies
# counts and hashes, validates configuration and runs the smoke suite.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

START_SECONDS=$SECONDS

usage() {
  cat <<'EOF'
Usage: scripts/restore.sh --from PATH [options]

  --from PATH              Backup directory, .tar.gz archive or .tar.gz.age archive (required)
  --identity PATH          age identity file for an encrypted archive
  --confirm                Required in a non-interactive shell
  --skip-objects           Do not restore S3 objects
  --skip-keycloak          Do not restore the Keycloak realm
  --skip-smoke             Do not run the post-restore smoke suite
  --allow-existing-realm   Import into a realm that already has users (overwrites them)

The application database, object buckets and Keycloak realm must be empty. Stop the
stack before a production restore drill and start it again afterwards. The script stops
the application and telemetry services it needs to restore and starts them again.
EOF
}

FROM=""
IDENTITY=""
SKIP_OBJECTS=0
SKIP_KEYCLOAK=0
SKIP_SMOKE=0
ALLOW_EXISTING_REALM=0

while (( $# > 0 )); do
  case "$1" in
    --from)
      [[ $# -ge 2 ]] || die "--from requires a value"
      FROM="$2"
      shift 2
      ;;
    --from=*) FROM="${1#*=}"; shift ;;
    --identity)
      [[ $# -ge 2 ]] || die "--identity requires a value"
      IDENTITY="$2"
      shift 2
      ;;
    --identity=*) IDENTITY="${1#*=}"; shift ;;
    --confirm) CONFIRM=1; shift ;;
    --skip-objects) SKIP_OBJECTS=1; shift ;;
    --skip-keycloak) SKIP_KEYCLOAK=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    --allow-existing-realm) ALLOW_EXISTING_REALM=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ -n "$FROM" ]] || die "--from is required"
[[ -e "$FROM" ]] || die "backup not found: $FROM"

require_env_file
require_cmd docker python3
activate_profile_from_env

PG_USER="$(env_value POSTGRES_USER sahyog)"
PG_DB="$(env_value POSTGRES_DB sahyog)"
for identifier in "$PG_USER" "$PG_DB"; do
  [[ "$identifier" =~ ^[A-Za-z0-9_]+$ ]] || die "invalid Postgres identifier: $identifier"
done
check_required_keys POSTGRES_PASSWORD >/dev/null || die "POSTGRES_PASSWORD is required"

TMP_ROOT=""
STOPPED_APP=""
STOPPED_AUX=""
cleanup() {
  local status=$?
  if (( status != 0 )); then
    if [[ -n "$STOPPED_APP" ]]; then
      warn "restarting application services after the failed restore"
      compose start $STOPPED_APP >/dev/null 2>&1 || true
    fi
    if [[ -n "$STOPPED_AUX" ]]; then
      warn "restarting telemetry services after the failed restore"
      compose start $STOPPED_AUX >/dev/null 2>&1 || true
    fi
  fi
  if [[ -n "$TMP_ROOT" ]]; then
    rm -rf "$TMP_ROOT"
  fi
}
trap cleanup EXIT

new_tmp_root() {
  if [[ -z "$TMP_ROOT" ]]; then
    TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/sahyog-restore.XXXXXX")"
    chmod 700 "$TMP_ROOT"
  fi
}

extract_archive() {
  local archive="$1" destination="$2"
  mkdir -p "$destination"
  python3 - "$archive" "$destination" <<'PY'
import sys
import tarfile
from pathlib import Path

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
with tarfile.open(archive, "r:gz") as handle:
    for member in handle.getmembers():
        parts = Path(member.name).parts
        if member.name.startswith("/") or ".." in parts:
            raise SystemExit(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk():
            raise SystemExit(f"unsafe archive link: {member.name}")
    kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
    handle.extractall(destination, **kwargs)
PY
}

BACKUP_DIR=""
TARBALL=""
case "$FROM" in
  *.age)
    [[ -n "$IDENTITY" ]] || die "--identity is required for an encrypted archive"
    [[ -f "$IDENTITY" ]] || die "age identity not found: $IDENTITY"
    require_cmd age
    new_tmp_root
    mkdir -p "$TMP_ROOT/archive" "$TMP_ROOT/restore"
    age --decrypt --identity "$IDENTITY" --output "$TMP_ROOT/archive/backup.tar.gz" "$FROM"
    TARBALL="$TMP_ROOT/archive/backup.tar.gz"
    extract_archive "$TARBALL" "$TMP_ROOT/restore"
    BACKUP_DIR="$TMP_ROOT/restore"
    ;;
  *.tar.gz | *.tgz)
    new_tmp_root
    mkdir -p "$TMP_ROOT/restore"
    extract_archive "$FROM" "$TMP_ROOT/restore"
    BACKUP_DIR="$TMP_ROOT/restore"
    ;;
  *)
    [[ -d "$FROM" ]] || die "--from must be a directory, .tar.gz or .tar.gz.age archive"
    BACKUP_DIR="$FROM"
    ;;
esac

if [[ ! -f "$BACKUP_DIR/manifest.json" ]]; then
  MANIFEST_CANDIDATE="$(python3 - "$BACKUP_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
matches = [
    path for path in root.rglob("manifest.json")
    if len(path.relative_to(root).parts) <= 2
]
if len(matches) != 1:
    raise SystemExit(f"expected one manifest.json, found {len(matches)}")
print(matches[0].parent)
PY
)" || die "backup manifest is missing or ambiguous"
  BACKUP_DIR="$MANIFEST_CANDIDATE"
fi
BACKUP_DIR="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$BACKUP_DIR")"
MANIFEST="$BACKUP_DIR/manifest.json"
[[ -f "$MANIFEST" ]] || die "backup manifest not found under $BACKUP_DIR"

step "Verifying backup integrity"
python3 - "$BACKUP_DIR" <<'PY' || die "backup integrity check failed"
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import PurePosixPath, Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("format") != 1:
    raise SystemExit(f"unsupported backup format: {manifest.get('format')}")
entries = manifest.get("files")
if not isinstance(entries, list) or not entries:
    raise SystemExit("manifest has no file hashes")
for entry in entries:
    relative = entry.get("path", "")
    parts = PurePosixPath(relative).parts
    if not relative or relative.startswith("/") or ".." in parts:
        raise SystemExit(f"unsafe manifest path: {relative}")
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"missing file: {relative}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != entry.get("sha256"):
        raise SystemExit(f"hash mismatch: {relative}")
    if path.stat().st_size != entry.get("bytes"):
        raise SystemExit(f"size mismatch: {relative}")
counts = (manifest.get("database") or {}).get("counts") or {}
for table in counts:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table):
        raise SystemExit(f"unsafe table name in manifest: {table}")
print(f"verified {len(entries)} files and {len(counts)} table counts")
PY

BACKUP_DB="$(python3 - "$MANIFEST" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
print((manifest.get("database") or {}).get("name", ""))
PY
)"
[[ -n "$BACKUP_DB" ]] || die "manifest does not name the application database"
[[ -f "$BACKUP_DIR/db/$BACKUP_DB.dump" ]] || die "application database dump is missing"

mapfile_buckets() {
  python3 - "$MANIFEST" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
objects = manifest.get("objects")
if isinstance(objects, dict):
    print(" ".join(sorted(objects)))
PY
}
BUCKETS="$(mapfile_buckets)"
DATABASES="$(python3 - "$MANIFEST" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
print(" ".join(manifest.get("databases") or []))
PY
)"

keycloak_value() {
  python3 - "$MANIFEST" "$1" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
keycloak = manifest.get("keycloak")
if not isinstance(keycloak, dict):
    print("")
else:
    value = keycloak.get(sys.argv[2], "")
    print("" if value is None else value)
PY
}
KEYCLOAK_REALM_NAME="$(keycloak_value realm)"
KEYCLOAK_USERS="$(keycloak_value users)"

if (( SKIP_OBJECTS == 0 )); then
  [[ -n "$BUCKETS" ]] || { warn "backup has no object section; skipping objects"; SKIP_OBJECTS=1; }
  if (( SKIP_OBJECTS == 0 )); then
    check_required_keys S3_ACCESS_KEY S3_SECRET_KEY >/dev/null ||
      die "S3_ACCESS_KEY and S3_SECRET_KEY are required to restore objects"
  fi
fi
if (( SKIP_KEYCLOAK == 0 )); then
  if [[ -z "$KEYCLOAK_REALM_NAME" ]]; then
    warn "backup has no Keycloak section; skipping the realm"
    SKIP_KEYCLOAK=1
  else
    check_required_keys KEYCLOAK_ADMIN_PASSWORD >/dev/null ||
      die "KEYCLOAK_ADMIN_PASSWORD is required to restore the realm"
  fi
fi

docker image inspect sahyog-api:local >/dev/null 2>&1 ||
  die "image sahyog-api:local not found; build it before restoring"

step "Checking the target environment"
wait_compose_healthy postgres 60 || die "postgres is not running; start the stack first"
if (( SKIP_OBJECTS == 0 )); then
  wait_compose_healthy s3proxy 60 || die "s3proxy is not running; start the stack first"
fi
if (( SKIP_KEYCLOAK == 0 )); then
  wait_compose_healthy keycloak 90 || die "keycloak is not running; start the stack first"
fi

APP_ROWS="$(compose exec -T postgres psql -At -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "
  SELECT coalesce(sum((xpath('/row/c/text()',
    query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, relname),
                 false, true, '')))[1]::text::bigint), 0)
  FROM pg_stat_user_tables
  WHERE schemaname = 'public' AND relname <> 'alembic_version'" | tr -d '[:space:]')"
[[ "$APP_ROWS" == "0" ]] ||
  die "database $PG_DB already contains $APP_ROWS rows; restore into an empty environment (use scripts/reset-db.sh --no-seed first)"

new_tmp_root
mkdir -p "$TMP_ROOT/probe"

if (( SKIP_KEYCLOAK == 0 )); then
  step "Checking the Keycloak realm"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$TMP_ROOT/probe:/work" api \
    sh -c 'python scripts/keycloak_admin.py status > /work/keycloak-before.json' ||
    die "could not read the Keycloak realm status"
  KEYCLOAK_STATE="$(python3 - "$TMP_ROOT/probe/keycloak-before.json" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
print(f"{1 if payload.get('exists') else 0} {int(payload.get('users', 0))}")
PY
)"
  KC_EXISTS="${KEYCLOAK_STATE%% *}"
  KC_USERS="${KEYCLOAK_STATE##* }"
  if [[ "$KC_EXISTS" == "1" && "$KC_USERS" != "0" && "$ALLOW_EXISTING_REALM" != "1" ]]; then
    die "realm already has $KC_USERS users; restore into an empty realm or pass --allow-existing-realm"
  fi
fi

if (( SKIP_OBJECTS == 0 )); then
  step "Checking that the object buckets are empty"
  : >"$TMP_ROOT/probe/target-counts.txt"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e RESTORE_BUCKETS="$BUCKETS" \
    -v "$TMP_ROOT/probe:/work" --entrypoint /bin/bash s3-init -c '
      set -euo pipefail
      export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
      export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
      export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
      export AWS_EC2_METADATA_DISABLED=true
      ENDPOINT="${S3_ENDPOINT_URL:-http://s3proxy:80}"
      for bucket in $RESTORE_BUCKETS; do
        count=0
        if aws --endpoint-url "$ENDPOINT" s3 ls "s3://$bucket" >/dev/null 2>&1; then
          count=$(aws --endpoint-url "$ENDPOINT" s3 ls "s3://$bucket" --recursive | wc -l | tr -d " ")
        fi
        echo "$bucket=$count" >> /work/target-counts.txt
      done
    ' || die "could not inspect the target buckets"
  NONEMPTY="$(awk -F= '$2 != 0 {print $1 "=" $2}' "$TMP_ROOT/probe/target-counts.txt")"
  [[ -z "$NONEMPTY" ]] ||
    die "object buckets are not empty ($NONEMPTY); restore into empty buckets first"
fi

step "Restore plan"
say "  Source           $BACKUP_DIR"
say "  Database         $BACKUP_DB -> $PG_DB"
say "  Telemetry DBs    ${DATABASES:-<none>}"
if (( SKIP_OBJECTS == 0 )); then
  say "  Buckets          $BUCKETS"
else
  say "  Buckets          <skipped>"
fi
if (( SKIP_KEYCLOAK == 0 )); then
  say "  Keycloak realm   $KEYCLOAK_REALM_NAME ($KEYCLOAK_USERS users in the backup)"
else
  say "  Keycloak realm   <skipped>"
fi
require_confirmation "Restoring will replace the empty application database and objects in this environment."

step "Stopping application services that hold database connections"
for service in api worker scheduler; do
  if compose_has_service "$service" && [[ -n "$(compose ps -q "$service" 2>/dev/null)" ]]; then
    STOPPED_APP="${STOPPED_APP:+$STOPPED_APP }$service"
  fi
done
if [[ -n "$STOPPED_APP" ]]; then
  compose stop $STOPPED_APP >/dev/null
fi

restore_database() {
  local database="$1" dump="$2"
  step "Restoring database $database"
  cat "$dump" | compose exec -T postgres pg_restore \
    --username "$PG_USER" --dbname "$database" \
    --no-owner --no-acl --clean --if-exists --single-transaction --exit-on-error
}

grant_auxiliary_privileges() {
  local database="$1" owner
  owner="$(compose exec -T postgres psql -At -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$database'")"
  [[ "$owner" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "could not resolve the owner of $database"
  compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$database" -c "
    GRANT ALL ON SCHEMA public TO \"$owner\";
    GRANT ALL ON ALL TABLES IN SCHEMA public TO \"$owner\";
    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO \"$owner\";
    GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO \"$owner\";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO \"$owner\";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO \"$owner\";
  " >/dev/null
}

db_exists() {
  local database="$1"
  compose exec -T postgres psql -At -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT 1 FROM pg_database WHERE datname = '$database'" | grep -qx 1
}

restore_database "$PG_DB" "$BACKUP_DIR/db/$BACKUP_DB.dump"

for database in $DATABASES; do
  [[ "$database" == "$BACKUP_DB" ]] && continue
  dump="$BACKUP_DIR/db/$database.dump"
  [[ -f "$dump" ]] || continue
  if ! db_exists "$database"; then
    warn "database $database is not configured in this environment; skipping its restore"
    continue
  fi
  for service in litellm langfuse-web langfuse-worker; do
    case "$service" in
      litellm) [[ "$database" == "litellm" ]] || continue ;;
      *) [[ "$database" == "langfuse" ]] || continue ;;
    esac
    if compose_has_service "$service" && [[ -n "$(compose ps -q "$service" 2>/dev/null)" ]]; then
      case " $STOPPED_AUX " in
        *" $service "*) ;;
        *) STOPPED_AUX="${STOPPED_AUX:+$STOPPED_AUX }$service" ;;
      esac
    fi
  done
done

if [[ -n "$STOPPED_AUX" ]]; then
  step "Stopping telemetry services for their database restore"
  compose stop $STOPPED_AUX >/dev/null
fi

for database in $DATABASES; do
  [[ "$database" == "$BACKUP_DB" ]] && continue
  dump="$BACKUP_DIR/db/$database.dump"
  [[ -f "$dump" ]] || continue
  if ! db_exists "$database"; then
    continue
  fi
  restore_database "$database" "$dump"
  grant_auxiliary_privileges "$database"
done

if [[ -n "$STOPPED_AUX" ]]; then
  step "Starting telemetry services"
  compose start $STOPPED_AUX >/dev/null
  STOPPED_AUX=""
fi

if (( SKIP_OBJECTS == 0 )); then
  step "Restoring object buckets"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e RESTORE_BUCKETS="$BUCKETS" \
    -v "$BACKUP_DIR/objects:/backup:ro" \
    --entrypoint /bin/bash s3-init -c '
      set -euo pipefail
      export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
      export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
      export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
      export AWS_EC2_METADATA_DISABLED=true
      ENDPOINT="${S3_ENDPOINT_URL:-http://s3proxy:80}"
      for bucket in $RESTORE_BUCKETS; do
        [ -d "/backup/$bucket" ] || continue
        aws --endpoint-url "$ENDPOINT" s3 mb "s3://$bucket" >/dev/null 2>&1 || true
        aws --endpoint-url "$ENDPOINT" s3 sync "/backup/$bucket" "s3://$bucket" >/dev/null
      done
    ' || die "object restore failed"
fi

if (( SKIP_KEYCLOAK == 0 )); then
  step "Restoring the Keycloak realm"
  compose run --rm --no-deps -T api \
    python scripts/keycloak_admin.py import --file - <"$BACKUP_DIR/keycloak/realm.json" ||
    die "Keycloak realm import failed"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$TMP_ROOT/probe:/work" api \
    sh -c 'python scripts/keycloak_admin.py status > /work/keycloak-after.json' ||
    die "could not read the Keycloak realm status after the restore"
  python3 - "$TMP_ROOT/probe/keycloak-after.json" "$KEYCLOAK_USERS" <<'PY' || die "Keycloak realm verification failed"
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
expected = int(sys.argv[2])
actual = int(payload.get("users", 0))
if not payload.get("exists"):
    raise SystemExit("realm does not exist after the restore")
if actual < expected:
    raise SystemExit(f"realm has {actual} users, expected at least {expected}")
if actual > expected:
    print(f"warning: realm has {actual} users, {expected} were in the backup", file=sys.stderr)
print(f"realm restored with {actual} users")
PY
fi

step "Bringing the schema to the current revision"
compose run --rm --no-deps -T -w /app/apps/api api alembic upgrade head ||
  die "migrations failed after the restore"

step "Verifying restored row counts"
python3 - "$MANIFEST" >"$TMP_ROOT/expected-counts.txt" <<'PY'
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
counts = (manifest.get("database") or {}).get("counts") or {}
for table, count in sorted(counts.items()):
    if table != "alembic_version":
        print(f"{table}={count}")
PY
COUNT_MISMATCH=0
while IFS='=' read -r table expected; do
  [[ -n "$table" ]] || continue
  actual="$(compose exec -T postgres psql -At -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM \"$table\";" | tr -d '[:space:]')"
  if [[ "$actual" != "$expected" ]]; then
    warn "row count mismatch for $table: expected $expected, found $actual"
    COUNT_MISMATCH=1
  fi
done <"$TMP_ROOT/expected-counts.txt"
(( COUNT_MISMATCH == 0 )) || die "restored row counts do not match the manifest"
ok "row counts match the backup"

if (( SKIP_OBJECTS == 0 )); then
  step "Verifying restored object counts"
  : >"$TMP_ROOT/probe/restored-counts.txt"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e RESTORE_BUCKETS="$BUCKETS" \
    -v "$TMP_ROOT/probe:/work" --entrypoint /bin/bash s3-init -c '
      set -euo pipefail
      export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
      export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
      export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
      export AWS_EC2_METADATA_DISABLED=true
      ENDPOINT="${S3_ENDPOINT_URL:-http://s3proxy:80}"
      for bucket in $RESTORE_BUCKETS; do
        count=$(aws --endpoint-url "$ENDPOINT" s3 ls "s3://$bucket" --recursive 2>/dev/null | wc -l | tr -d " ")
        echo "$bucket=$count" >> /work/restored-counts.txt
      done
    ' || die "could not verify the restored buckets"
  python3 - "$MANIFEST" "$TMP_ROOT/probe/restored-counts.txt" <<'PY' || die "restored object counts do not match the manifest"
import json
import sys

manifest = json.loads(open(sys.argv[1], encoding="utf-8").read())
expected = manifest.get("objects") or {}
actual = {}
for line in open(sys.argv[2], encoding="utf-8"):
    if "=" in line:
        bucket, _, value = line.strip().partition("=")
        actual[bucket] = int(value)
mismatches = [
    f"{bucket}: expected {count}, found {actual.get(bucket, 0)}"
    for bucket, count in expected.items()
    if actual.get(bucket, 0) != count
]
if mismatches:
    raise SystemExit("; ".join(mismatches))
print(f"verified {sum(expected.values())} objects in {len(expected)} buckets")
PY
fi

if [[ -n "$STOPPED_APP" ]]; then
  step "Starting application services"
  compose start $STOPPED_APP >/dev/null
  STOPPED_APP=""
fi

step "Validating configuration, flags, model routes and the FinOps model"
compose_run_api python scripts/validate_config.py

if (( SKIP_SMOKE == 0 )); then
  step "Running the smoke suite"
  "$ROOT/scripts/smoke.sh" --sources --notifications --analytics --flags --skip-ui --summary ||
    die "restore completed but the smoke suite failed"
fi

ELAPSED=$((SECONDS - START_SECONDS))
ok "restore complete in ${ELAPSED}s"
if (( ELAPSED > 14400 )); then
  warn "restore exceeded the four-hour recovery target"
fi
dim "Review the smoke output and record the drill in the operations log."
