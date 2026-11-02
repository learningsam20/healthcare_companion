#!/usr/bin/env bash
# Render/schema smoke for the app-tier HA overlay. This does not test failover.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RENDERED="$ROOT/deploy/k8s/rendered/ha.yaml"
EVIDENCE="$ROOT/docs/evidence/k8s-ha-smoke-$STAMP.json"
OVERLAY="$ROOT/deploy/k8s/overlays/ha"

mkdir -p "$(dirname "$RENDERED")" "$(dirname "$EVIDENCE")"
if command -v kustomize >/dev/null 2>&1; then
  kustomize build "$OVERLAY" >"$RENDERED"
elif command -v kubectl >/dev/null 2>&1; then
  kubectl kustomize "$OVERLAY" >"$RENDERED"
else
  printf 'error: kustomize or kubectl is required\n' >&2
  exit 2
fi

KUBECONFORM_AVAILABLE=false
KUBECONFORM_STATUS=not_available
if command -v kubeconform >/dev/null 2>&1; then
  KUBECONFORM_AVAILABLE=true
  kubeconform -strict -summary "$RENDERED"
  KUBECONFORM_STATUS=passed
fi

python3 - "$ROOT/docs/evidence/k8s-ha-smoke-TEMPLATE.json" "$EVIDENCE" \
  "$RENDERED" "$KUBECONFORM_AVAILABLE" "$KUBECONFORM_STATUS" <<'PY'
import datetime
import json
import pathlib
import sys

template, output, rendered, available, status = sys.argv[1:]
payload = json.loads(pathlib.Path(template).read_text(encoding="utf-8"))
payload["generated_at"] = datetime.datetime.now(datetime.UTC).isoformat()
payload["rendered_manifest"] = str(pathlib.Path(rendered))
payload["render_status"] = "passed"
payload["kubeconform"] = {"available": available == "true", "status": status}
pathlib.Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY

printf 'Evidence JSON: %s\n' "$EVIDENCE"
printf 'Note: manifest smoke only; failover was not tested.\n'
