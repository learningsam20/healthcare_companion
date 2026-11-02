#!/usr/bin/env bash
# Render, validate and optionally apply the Kubernetes overlays.
#
# Rendering is the default. Nothing is sent to a cluster unless --confirm is
# given. The script never prints secret values and never creates a Secret over
# an existing one.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/k8s-deploy.sh [options]

  --overlay pilot|production  Overlay to render (default: pilot)
  --namespace NAME            Expected namespace (default: sahyog)
  --context NAME              kubectl context to use
  --api-image REF             API image reference, tag or digest
  --web-image REF             Web image reference, tag or digest
  --create-secret-from-env    Create sahyog-secrets from .env if it is absent
  --confirm                   Apply to the cluster (otherwise render only)
  --no-wait                   Do not wait for rollouts and jobs after apply
  --timeout SECONDS           Rollout/job timeout (default: 600)
  --allow-drift               Skip the copied-config drift check
  --output PATH               Render destination (default: deploy/k8s/rendered/<overlay>.yaml)

Rendering validates the overlay and writes a single YAML file. Applying first
runs a server-side dry run, then deletes completed bootstrap Jobs so an image or
spec change can be re-applied safely.

The namespace is pinned in the manifests. A different --namespace is rejected
rather than silently ignored.
EOF
}

OVERLAY="pilot"
NAMESPACE="sahyog"
CONTEXT=""
API_IMAGE=""
WEB_IMAGE=""
CREATE_SECRET=0
WAIT=1
TIMEOUT=600
ALLOW_DRIFT=0
OUTPUT=""
CONFIRM="${CONFIRM:-0}"

while (( $# > 0 )); do
  case "$1" in
    --overlay)
      [[ $# -ge 2 ]] || die "--overlay requires a value"
      OVERLAY="$2"
      shift 2
      ;;
    --overlay=*)
      OVERLAY="${1#*=}"
      shift
      ;;
    --namespace)
      [[ $# -ge 2 ]] || die "--namespace requires a value"
      NAMESPACE="$2"
      shift 2
      ;;
    --namespace=*)
      NAMESPACE="${1#*=}"
      shift
      ;;
    --context)
      [[ $# -ge 2 ]] || die "--context requires a value"
      CONTEXT="$2"
      shift 2
      ;;
    --context=*)
      CONTEXT="${1#*=}"
      shift
      ;;
    --api-image)
      [[ $# -ge 2 ]] || die "--api-image requires a value"
      API_IMAGE="$2"
      shift 2
      ;;
    --api-image=*)
      API_IMAGE="${1#*=}"
      shift
      ;;
    --web-image)
      [[ $# -ge 2 ]] || die "--web-image requires a value"
      WEB_IMAGE="$2"
      shift 2
      ;;
    --web-image=*)
      WEB_IMAGE="${1#*=}"
      shift
      ;;
    --create-secret-from-env)
      CREATE_SECRET=1
      shift
      ;;
    --confirm)
      CONFIRM=1
      shift
      ;;
    --no-wait)
      WAIT=0
      shift
      ;;
    --timeout)
      [[ $# -ge 2 ]] || die "--timeout requires a value"
      TIMEOUT="$2"
      shift 2
      ;;
    --timeout=*)
      TIMEOUT="${1#*=}"
      shift
      ;;
    --allow-drift)
      ALLOW_DRIFT=1
      shift
      ;;
    --output)
      [[ $# -ge 2 ]] || die "--output requires a value"
      OUTPUT="$2"
      shift 2
      ;;
    --output=*)
      OUTPUT="${1#*=}"
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

case "$OVERLAY" in
  pilot | production) ;;
  *) die "unknown overlay: $OVERLAY (expected pilot or production)" ;;
esac

[[ "$NAMESPACE" == "sahyog" ]] ||
  die "the manifests pin namespace sahyog; change base/kustomization.yaml and the overlays together before using --namespace $NAMESPACE"

[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || die "--timeout must be an integer number of seconds"

OVERLAY_DIR="$ROOT/deploy/k8s/overlays/$OVERLAY"
[[ -d "$OVERLAY_DIR" ]] || die "missing overlay directory: $OVERLAY_DIR"

RENDER_DIR="$ROOT/deploy/k8s/rendered"
OUTPUT="${OUTPUT:-$RENDER_DIR/$OVERLAY.yaml}"
mkdir -p "$(dirname "$OUTPUT")"

require_cmd kubectl python3

KUBECTL=(kubectl)
if [[ -n "$CONTEXT" ]]; then
  KUBECTL+=(--context "$CONTEXT")
fi

TMP_CLEANUP=""
cleanup() {
  [[ -z "$TMP_CLEANUP" ]] || rm -rf "$TMP_CLEANUP"
}
trap cleanup EXIT

check_drift() {
  local mismatches=0 src dst
  while IFS='|' read -r src dst; do
    [[ -n "$src" ]] || continue
    if [[ ! -f "$ROOT/$src" || ! -f "$ROOT/$dst" ]]; then
      warn "missing config copy: $src -> $dst"
      mismatches=$((mismatches + 1))
      continue
    fi
    if ! cmp -s "$ROOT/$src" "$ROOT/$dst"; then
      warn "config drift: $src and $dst differ"
      diff -u "$ROOT/$src" "$ROOT/$dst" >&2 || true
      mismatches=$((mismatches + 1))
    fi
  done <<EOF
docker/postgres/init.sh|deploy/k8s/base/config/postgres-init.sh
docker/s3proxy/init.sh|deploy/k8s/base/config/s3-init.sh
config/litellm.yaml|deploy/k8s/base/config/litellm.yaml
docker/otel/config.yaml|deploy/k8s/components/observability/config/otel-config.yaml
docker/prometheus/prometheus.yml|deploy/k8s/components/observability/config/prometheus.yml
docker/grafana/provisioning/datasources/prometheus.yml|deploy/k8s/components/observability/config/grafana-datasource.yaml
docker/egress/squid.conf|deploy/k8s/components/observability/config/squid.conf
EOF
  if (( mismatches > 0 )); then
    die "copied Kustomize configs are stale; recopy them or pass --allow-drift"
  fi
}

image_entry() {
  local key="$1" ref="$2" new_name new_tag digest last
  [[ "$ref" =~ ^[A-Za-z0-9._/@:-]+$ ]] || die "invalid image reference: $ref"
  if [[ "$ref" == *"@"* ]]; then
    new_name="${ref%%@*}"
    digest="${ref#*@}"
    [[ "$digest" == sha256:* ]] || die "only sha256 digests are supported: $ref"
    printf '  - name: %s\n    newName: %s\n    digest: %s\n' "$key" "$new_name" "$digest"
    return 0
  fi
  last="${ref##*/}"
  [[ "$last" == *:* ]] || die "image reference must include a tag or digest: $ref"
  new_name="${ref%:*}"
  new_tag="${ref##*:}"
  printf '  - name: %s\n    newName: %s\n    newTag: %s\n' "$key" "$new_name" "$new_tag"
}

render() {
  if [[ -z "$API_IMAGE" && -z "$WEB_IMAGE" ]]; then
    kubectl kustomize "$OVERLAY_DIR" >"$OUTPUT"
    return 0
  fi
  local tmp
  # Kustomize rejects absolute resource paths. A sibling directory keeps the
  # reference relative; the relaxed load restrictor allows the ../overlay hop.
  tmp="$(mktemp -d "$ROOT/deploy/k8s/overlays/.render.XXXXXX")"
  TMP_CLEANUP="$tmp"
  {
    printf 'apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - ../%s\nimages:\n' "$OVERLAY"
    [[ -z "$API_IMAGE" ]] || image_entry sahyog-api "$API_IMAGE"
    [[ -z "$WEB_IMAGE" ]] || image_entry sahyog-web "$WEB_IMAGE"
  } >"$tmp/kustomization.yaml"
  kubectl kustomize --load-restrictor LoadRestrictionsNone "$tmp" >"$OUTPUT"
}

summary() {
  local total
  total="$(grep -c '^kind: ' "$OUTPUT" || true)"
  say ""
  say "  rendered $total resources to $OUTPUT"
  awk '/^kind: /{counts[$2]++} END {for (kind in counts) printf "    %-28s %d\n", kind, counts[kind]}' \
    "$OUTPUT" | sort
}

create_secret_from_env() {
  require_env_file
  validate_profile_env full
  check_required_keys DATABASE_URL LITELLM_DATABASE_URL LANGFUSE_DATABASE_URL ||
    die "database URLs are required for the Kubernetes Secret"

  if "${KUBECTL[@]}" -n "$NAMESPACE" get secret sahyog-secrets >/dev/null 2>&1; then
    warn "sahyog-secrets already exists; leaving it unchanged (rotate deliberately, not by redeploy)"
    return 0
  fi
  if [[ "$CONFIRM" != "1" ]]; then
    dim "  would create sahyog-secrets from $ENV_FILE (not applied without --confirm)"
    return 0
  fi
  python3 - "$ENV_FILE" <<'PY' | "${KUBECTL[@]}" apply -f - >/dev/null
import json
import os
import sys
from urllib.parse import urlparse

path = sys.argv[1]
values: dict[str, str] = {}
with open(path, encoding="utf-8") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            for index, char in enumerate(value):
                if char == "#" and (index == 0 or value[index - 1] in " \t"):
                    value = value[:index].rstrip()
                    break
        values[name] = value

required = [
    "POSTGRES_PASSWORD", "DATABASE_URL", "LITELLM_DB_PASSWORD", "LITELLM_DATABASE_URL",
    "LANGFUSE_DB_PASSWORD", "LANGFUSE_DATABASE_URL", "KEYCLOAK_DB_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD", "KEYCLOAK_ADMIN_CLIENT_SECRET",
    "KEYCLOAK_CLI_CLIENT_SECRET", "KEYCLOAK_MCP_CLIENT_SECRET", "APP_SECRET_KEY",
    "PII_TOKEN_SECRET", "MCP_CONTEXT_SECRET", "MCP_SERVICE_TOKEN", "LITELLM_MASTER_KEY",
    "S3_ACCESS_KEY", "S3_SECRET_KEY",
    "LANGFUSE_NEXTAUTH_SECRET", "LANGFUSE_SALT", "LANGFUSE_ENCRYPTION_KEY",
    "GRAFANA_ADMIN_PASSWORD", "SEED_DEMO_PASSWORD",
]
optional = [
    "OPENROUTER_API_KEY", "SMTP_PASSWORD", "SLACK_BOT_TOKEN", "SMS_API_KEY",
    "FHIR_CLIENT_SECRET", "ADD_USER_PASSWORD",
]

missing = [key for key in required if not os.environ.get(key, values.get(key, "")).strip()]
if missing:
    sys.exit("missing required keys in .env: " + ", ".join(missing))

for key in ("DATABASE_URL", "LITELLM_DATABASE_URL", "LANGFUSE_DATABASE_URL"):
    url = os.environ.get(key, values.get(key, ""))
    if urlparse(url).hostname != "postgres":
        sys.exit(f"{key} must target the in-cluster host 'postgres' for Kubernetes")

data = {key: os.environ.get(key, values.get(key, "")) for key in required}
for key in optional:
    value = os.environ.get(key, values.get(key, ""))
    if value:
        data[key] = value

secret = {
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {
        "name": "sahyog-secrets",
        "namespace": "sahyog",
        "labels": {"app.kubernetes.io/part-of": "sahyog"},
    },
    "type": "Opaque",
    "stringData": data,
}
json.dump(secret, sys.stdout)
PY
  ok "sahyog-secrets created from $ENV_FILE (values were not printed)"
}

prepare_jobs() {
  local job active
  for job in sahyog-migrate s3-init keycloak-sync; do
    if "${KUBECTL[@]}" -n "$NAMESPACE" get "job/$job" >/dev/null 2>&1; then
      active="$("${KUBECTL[@]}" -n "$NAMESPACE" get "job/$job" -o jsonpath='{.status.active}' 2>/dev/null || true)"
      if [[ -n "$active" ]]; then
        die "job/$job is still active; wait for it to finish before redeploying"
      fi
      "${KUBECTL[@]}" -n "$NAMESPACE" delete "job/$job" --wait=true >/dev/null
      dim "  removed completed job/$job so it can be re-created"
    fi
  done
}

apply_render() {
  local context
  context="$("${KUBECTL[@]}" config current-context 2>/dev/null || true)"
  [[ -n "$context" ]] || die "kubectl has no current context"
  require_confirmation "Apply $OVERLAY to context '$context', namespace '$NAMESPACE'?"
  create_secret_from_env
  if ! "${KUBECTL[@]}" -n "$NAMESPACE" get secret sahyog-secrets >/dev/null 2>&1; then
    die "sahyog-secrets is missing; create it first or pass --create-secret-from-env"
  fi
  prepare_jobs

  step "Server-side dry run"
  "${KUBECTL[@]}" apply --dry-run=server -f "$OUTPUT" >/dev/null ||
    die "server-side dry run failed; nothing was applied"

  step "Applying $OVERLAY"
  "${KUBECTL[@]}" apply -f "$OUTPUT"
  ok "manifests applied"

  if (( WAIT == 0 )); then
    dim "  --no-wait: skipping rollout status"
    return 0
  fi

  step "Waiting for workloads (timeout ${TIMEOUT}s)"
  local deployment
  for deployment in api web worker mcp-broker keycloak litellm; do
    if ! "${KUBECTL[@]}" -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout="${TIMEOUT}s"; then
      warn "deployment/$deployment did not become ready"
      "${KUBECTL[@]}" -n "$NAMESPACE" get pods -l "app.kubernetes.io/name=$deployment" -o wide >&2 || true
      warn "inspect with ./scripts/k8s-status.sh --namespace $NAMESPACE"
      return 1
    fi
  done

  step "Waiting for bootstrap jobs (timeout ${TIMEOUT}s)"
  local job
  for job in sahyog-migrate s3-init keycloak-sync; do
    if ! "${KUBECTL[@]}" -n "$NAMESPACE" wait --for=condition=complete "job/$job" --timeout="${TIMEOUT}s"; then
      warn "job/$job did not complete; inspect its logs before continuing"
      return 1
    fi
  done
  ok "rollouts and bootstrap jobs completed"
}

if (( ALLOW_DRIFT == 0 )); then
  step "Checking copied configuration"
  check_drift
  ok "Kustomize config copies match their sources"
fi

step "Rendering $OVERLAY"
render
ok "overlay rendered"
summary

if [[ "$CONFIRM" != "1" ]]; then
  say ""
  dim "  Render only. Re-run with --confirm to apply."
  if (( CREATE_SECRET == 1 )); then
    dim "  sahyog-secrets would be created from $ENV_FILE if it is absent; nothing was sent to a cluster."
  fi
  exit 0
fi

apply_render
