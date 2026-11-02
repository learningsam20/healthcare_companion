#!/usr/bin/env bash
# Back up the application database, object buckets, Keycloak realm and versioned config.
# The archive contains PHI and Keycloak client secrets; encrypt it before it leaves the host.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
umask 077

usage() {
  cat <<'EOF'
Usage: scripts/backup.sh --out DIR [options]

  --out DIR            Empty or new directory outside this repository (required)
  --encrypt RECIPIENT  Encrypt the archive with age to this public key/recipient
  --skip-objects       Do not copy S3 objects (database and Keycloak only)
  --skip-keycloak      Do not export the Keycloak realm
  --note TEXT          Short non-PHI note stored in the manifest

The backup contains the application database (plus LiteLLM/Langfuse databases when
present), all six object buckets, a Keycloak realm export and versioned config. It also
records SHA-256 hashes, row/object counts, the schema revision and the release version.
EOF
}

OUT=""
ENCRYPT_RECIPIENT=""
SKIP_OBJECTS=0
SKIP_KEYCLOAK=0
NOTE=""

while (( $# > 0 )); do
  case "$1" in
    --out)
      [[ $# -ge 2 ]] || die "--out requires a value"
      OUT="$2"
      shift 2
      ;;
    --out=*) OUT="${1#*=}"; shift ;;
    --encrypt)
      [[ $# -ge 2 ]] || die "--encrypt requires a recipient"
      ENCRYPT_RECIPIENT="$2"
      shift 2
      ;;
    --encrypt=*) ENCRYPT_RECIPIENT="${1#*=}"; shift ;;
    --skip-objects) SKIP_OBJECTS=1; shift ;;
    --skip-keycloak) SKIP_KEYCLOAK=1; shift ;;
    --note)
      [[ $# -ge 2 ]] || die "--note requires a value"
      NOTE="$2"
      shift 2
      ;;
    --note=*) NOTE="${1#*=}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ -n "$OUT" ]] || die "--out is required"
[[ "$OUT" != "/" ]] || die "refusing to use / as a backup directory"

require_env_file
require_cmd docker python3
activate_profile_from_env

PG_USER="$(env_value POSTGRES_USER sahyog)"
PG_DB="$(env_value POSTGRES_DB sahyog)"
APP_VERSION="$(env_value APP_VERSION 0.1.0)"
check_required_keys POSTGRES_PASSWORD >/dev/null || die "POSTGRES_PASSWORD is required"
for identifier in "$PG_USER" "$PG_DB"; do
  [[ "$identifier" =~ ^[A-Za-z0-9_]+$ ]] || die "invalid Postgres identifier: $identifier"
done

ROOT_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ROOT")"
OUT="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$OUT")"
case "$OUT/" in
  "$ROOT_REAL"/*) die "refusing to write a backup inside the repository; choose a path outside $ROOT_REAL" ;;
esac
if [[ -e "$OUT" && ! -d "$OUT" ]]; then
  die "backup path exists and is not a directory: $OUT"
fi
if [[ -d "$OUT" && -n "$(ls -A "$OUT" 2>/dev/null)" ]]; then
  die "backup directory is not empty: $OUT"
fi

if (( SKIP_OBJECTS == 0 )); then
  check_required_keys S3_ACCESS_KEY S3_SECRET_KEY >/dev/null ||
    die "S3_ACCESS_KEY and S3_SECRET_KEY are required to back up objects"
fi
if (( SKIP_KEYCLOAK == 0 )); then
  check_required_keys KEYCLOAK_ADMIN_PASSWORD >/dev/null ||
    die "KEYCLOAK_ADMIN_PASSWORD is required to export the realm"
  docker image inspect sahyog-api:local >/dev/null 2>&1 ||
    die "image sahyog-api:local not found; run scripts/start.sh once before backing up"
fi
if [[ -n "$ENCRYPT_RECIPIENT" ]]; then
  require_cmd age tar
fi

BUCKETS=""
add_bucket() {
  local bucket="$1"
  [[ "$bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || die "invalid bucket name: $bucket"
  BUCKETS="${BUCKETS:+$BUCKETS }$bucket"
}
add_bucket "$(env_value S3_BUCKET_DOCUMENTS sahyog-documents)"
add_bucket "$(env_value S3_BUCKET_AUDIO sahyog-audio)"
add_bucket "$(env_value S3_BUCKET_EXPORTS sahyog-exports)"
add_bucket "$(env_value S3_BUCKET_ANCHORS sahyog-audit-anchors)"
add_bucket "$(env_value S3_BUCKET_EVAL sahyog-eval)"
add_bucket "$(env_value S3_BUCKET_BACKUPS sahyog-backups)"

mkdir -p "$OUT/db" "$OUT/objects" "$OUT/keycloak" "$OUT/versioned/config" \
  "$OUT/versioned/keycloak"
chmod 700 "$OUT"

step "Checking the stack"
wait_compose_healthy postgres 30 || die "postgres is not running; start the stack first"
if (( SKIP_OBJECTS == 0 )); then
  wait_compose_healthy s3proxy 30 || die "s3proxy is not running; start the stack first"
fi
if (( SKIP_KEYCLOAK == 0 )); then
  wait_compose_healthy keycloak 60 || die "keycloak is not running; start the stack first"
fi

db_exists() {
  local database="$1"
  compose exec -T postgres psql -At -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT 1 FROM pg_database WHERE datname = '$database'" | grep -qx 1
}

dump_database() {
  local database="$1" destination="$OUT/db/$1.dump"
  step "Dumping database $database"
  compose exec -T postgres pg_dump \
    --username "$PG_USER" --dbname "$database" \
    --format=custom --compress=9 --no-owner --no-acl >"$destination"
  [[ -s "$destination" ]] || die "database dump is empty: $database"
  chmod 600 "$destination"
}

step "Dumping databases"
db_exists "$PG_DB" || die "application database does not exist: $PG_DB"
dump_database "$PG_DB"
DATABASES="$PG_DB"
for auxiliary in litellm langfuse; do
  if db_exists "$auxiliary"; then
    dump_database "$auxiliary"
    DATABASES="$DATABASES $auxiliary"
  else
    warn "database $auxiliary does not exist in this profile; skipping"
  fi
done

step "Recording schema revision and row counts"
compose exec -T postgres psql -At -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 \
  -c "SELECT version_num FROM alembic_version LIMIT 1" >"$OUT/db/revision.txt" 2>/dev/null ||
  : >"$OUT/db/revision.txt"
compose exec -T postgres psql -At -F '=' -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "
  SELECT relname,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, relname),
                             false, true, '')))[1]::text
  FROM pg_stat_user_tables
  WHERE schemaname = 'public'
  ORDER BY relname" >"$OUT/db/$PG_DB.counts.tsv"
chmod 600 "$OUT/db"/*

if (( SKIP_OBJECTS == 0 )); then
  step "Copying object buckets"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e BACKUP_BUCKETS="$BUCKETS" \
    -v "$OUT/objects:/backup" \
    --entrypoint /bin/bash s3-init -c '
      set -euo pipefail
      export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
      export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
      export AWS_DEFAULT_REGION="${S3_REGION:-us-east-1}"
      export AWS_EC2_METADATA_DISABLED=true
      ENDPOINT="${S3_ENDPOINT_URL:-http://s3proxy:80}"
      for bucket in $BACKUP_BUCKETS; do
        if ! aws --endpoint-url "$ENDPOINT" s3 ls "s3://$bucket" >/dev/null 2>&1; then
          echo "warning: bucket $bucket does not exist" >&2
          continue
        fi
        mkdir -p "/backup/$bucket"
        aws --endpoint-url "$ENDPOINT" s3 sync "s3://$bucket" "/backup/$bucket" >/dev/null
      done
    '
  : >"$OUT/object-counts.txt"
  for bucket in $BUCKETS; do
    count=0
    if [[ -d "$OUT/objects/$bucket" ]]; then
      count="$(find "$OUT/objects/$bucket" -type f | wc -l | tr -d ' ')"
    fi
    printf '%s=%s\n' "$bucket" "$count" >>"$OUT/object-counts.txt"
  done
else
  warn "object backup skipped"
fi

if (( SKIP_KEYCLOAK == 0 )); then
  step "Exporting the Keycloak realm"
  compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$OUT/keycloak:/backup" api \
    python scripts/keycloak_admin.py export --out /backup/realm.json
  python3 - "$OUT/keycloak/realm.json" <<'PY' || die "Keycloak export is not valid JSON"
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
if not isinstance(payload, dict):
    raise SystemExit("realm export is not a JSON object")
PY
  chmod 600 "$OUT/keycloak/realm.json"
else
  warn "Keycloak export skipped"
fi

step "Copying versioned configuration"
cp -R "$ROOT/config/." "$OUT/versioned/config/"
cp "$ROOT/docker-compose.yml" "$OUT/versioned/docker-compose.yml"
cp -R "$ROOT/docker/keycloak/." "$OUT/versioned/keycloak/"
if [[ -f "$ROOT/.env.example" ]]; then
  cp "$ROOT/.env.example" "$OUT/versioned/env.example"
fi

step "Writing the manifest"
SOURCE_SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'unversioned')"
IMAGE_ID="$(docker image inspect sahyog-api:local --format '{{.Id}}' 2>/dev/null || printf '')"
python3 - "$OUT" "$PG_DB" "$DATABASES" "$APP_VERSION" "$SOURCE_SHA" "$IMAGE_ID" "$NOTE" <<'PY'
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
app_db = sys.argv[2]
databases = sys.argv[3].split()
app_version, source_sha, image_id, note = sys.argv[4:8]

counts: dict[str, int] = {}
counts_path = root / "db" / f"{app_db}.counts.tsv"
if counts_path.is_file():
    for line in counts_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        table, _, value = line.partition("=")
        try:
            counts[table] = int(value)
        except ValueError:
            continue

objects: dict[str, int] | None = None
object_counts = root / "object-counts.txt"
if object_counts.is_file():
    objects = {}
    for line in object_counts.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        bucket, _, value = line.partition("=")
        try:
            objects[bucket] = int(value)
        except ValueError:
            continue

keycloak = None
realm_path = root / "keycloak" / "realm.json"
if realm_path.is_file():
    payload = json.loads(realm_path.read_text(encoding="utf-8"))
    keycloak = {
        "realm": payload.get("realm"),
        "users": len(payload.get("users", [])),
        "clients": len(payload.get("clients", [])),
        "path": "keycloak/realm.json",
    }

files = []
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.name == "manifest.json":
        continue
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    files.append(
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        }
    )

manifest = {
    "format": 1,
    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "note": note,
    "release": {
        "app_version": app_version,
        "source_sha": source_sha,
        "api_image_id": image_id,
        "alembic_revision": (root / "db" / "revision.txt").read_text(encoding="utf-8").strip()
        if (root / "db" / "revision.txt").is_file()
        else "",
    },
    "database": {"name": app_db, "counts": counts},
    "databases": databases,
    "objects": objects,
    "keycloak": keycloak,
    "files": files,
    "warning": "Contains PHI and Keycloak client secrets. Encrypt at rest and restrict access.",
}
(root / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
(root / "manifest.json").chmod(0o600)
print(
    f"manifest: {len(files)} files, {sum(entry['bytes'] for entry in files)} bytes, "
    f"{len(counts)} tables"
)
PY

chmod 600 "$OUT/manifest.json" 2>/dev/null || true
chmod -R go-rwx "$OUT"

if [[ -n "$ENCRYPT_RECIPIENT" ]]; then
  step "Encrypting the archive"
  ARCHIVE="$OUT.tar.gz"
  tar -C "$(dirname "$OUT")" -czf "$ARCHIVE" "$(basename "$OUT")"
  age --recipient "$ENCRYPT_RECIPIENT" --output "$ARCHIVE.age" "$ARCHIVE"
  [[ -s "$ARCHIVE.age" ]] || die "encryption produced no output; plaintext backup left at $OUT"
  chmod 600 "$ARCHIVE.age"
  rm -rf "$OUT" "$ARCHIVE"
  ok "encrypted backup written to $ARCHIVE.age"
  dim "Keep the age identity offline; restore needs --identity."
else
  warn "backup contains PHI and secrets and is NOT encrypted; encrypt it at rest or rerun with --encrypt"
  ok "backup written to $OUT"
fi

if [[ -n "$ENCRYPT_RECIPIENT" ]]; then
  du -sh "$OUT.tar.gz.age" 2>/dev/null || true
else
  du -sh "$OUT" 2>/dev/null || true
fi
