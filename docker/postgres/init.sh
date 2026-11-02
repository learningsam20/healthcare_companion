#!/usr/bin/env bash
# Runs once on an empty Postgres volume. The application database is created by the
# image entrypoint; this script creates the auxiliary roles/databases and extensions.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'litellm') THEN
    CREATE ROLE litellm LOGIN PASSWORD '${LITELLM_DB_PASSWORD}';
  ELSE
    ALTER ROLE litellm WITH LOGIN PASSWORD '${LITELLM_DB_PASSWORD}';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'langfuse') THEN
    CREATE ROLE langfuse LOGIN PASSWORD '${LANGFUSE_DB_PASSWORD}';
  ELSE
    ALTER ROLE langfuse WITH LOGIN PASSWORD '${LANGFUSE_DB_PASSWORD}';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'keycloak') THEN
    CREATE ROLE keycloak LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
  ELSE
    ALTER ROLE keycloak WITH LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
  END IF;
END
\$\$;
SQL

for spec in "litellm:litellm" "langfuse:langfuse" "keycloak:keycloak"; do
  database="${spec%%:*}"
  owner="${spec##*:}"
  if ! psql -tAc "SELECT 1 FROM pg_database WHERE datname='${database}'" --username "$POSTGRES_USER" | grep -q 1; then
    createdb --username "$POSTGRES_USER" --owner "$owner" "$database"
  fi
done

# Langfuse and Keycloak need UUID helpers; pgcrypto is per-database.
for database in langfuse keycloak; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$database" \
    -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
done
