#!/usr/bin/env bash
# Read-only cluster status for the sahyog namespace. Safe to run at any time.
# Never prints Secret data or environment variables.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/k8s-status.sh [options]

  --namespace NAME  Namespace to inspect (default: sahyog)
  --context NAME    kubectl context to use
  --json            Machine-readable output
  --strict          Exit 1 when a workload, pod or job is unhealthy
  -h, --help        Show this help

The command is read-only: it runs kubectl get against pods, workloads, Jobs,
Ingress, HPAs, PDBs, nodes and warning events.
EOF
}

NAMESPACE="sahyog"
CONTEXT=""
JSON=0
STRICT=0

while (( $# > 0 )); do
  case "$1" in
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
    --json)
      JSON=1
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_cmd kubectl python3

KUBECTL=(kubectl)
if [[ -n "$CONTEXT" ]]; then
  KUBECTL+=(--context "$CONTEXT")
fi

"${KUBECTL[@]}" version --client >/dev/null 2>&1 || die "kubectl is not usable"
if ! "${KUBECTL[@]}" get namespace "$NAMESPACE" >/dev/null 2>&1; then
  die "namespace $NAMESPACE is not reachable from context '$("${KUBECTL[@]}" config current-context 2>/dev/null || echo unknown)'"
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

context_name="$("${KUBECTL[@]}" config current-context 2>/dev/null || true)"
"${KUBECTL[@]}" get nodes -o json >"$tmpdir/nodes.json" 2>/dev/null || printf '{}\n' >"$tmpdir/nodes.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get pods -o json >"$tmpdir/pods.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get deployments -o json >"$tmpdir/deployments.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get statefulsets -o json >"$tmpdir/statefulsets.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get jobs -o json >"$tmpdir/jobs.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get ingress -o json >"$tmpdir/ingress.json" 2>/dev/null || printf '{}\n' >"$tmpdir/ingress.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get hpa -o json >"$tmpdir/hpa.json" 2>/dev/null || printf '{}\n' >"$tmpdir/hpa.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get pdb -o json >"$tmpdir/pdb.json" 2>/dev/null || printf '{}\n' >"$tmpdir/pdb.json"
"${KUBECTL[@]}" -n "$NAMESPACE" get events --field-selector type=Warning -o json >"$tmpdir/events.json" 2>/dev/null || printf '{}\n' >"$tmpdir/events.json"

python3 - "$tmpdir" "$NAMESPACE" "$context_name" "$JSON" "$STRICT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

directory = Path(sys.argv[1])
namespace = sys.argv[2]
context = sys.argv[3]
as_json = sys.argv[4] == "1"
strict = sys.argv[5] == "1"


def load(name):
    try:
        return json.loads((directory / name).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return {"items": []}


def items(name):
    return load(name).get("items") or []


def age(timestamp):
    if not timestamp:
        return "-"
    try:
        then = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "-"
    seconds = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


nodes = []
for node in items("nodes.json"):
    conditions = {c.get("type"): c.get("status") for c in node.get("status", {}).get("conditions", [])}
    nodes.append(
        {
            "name": node["metadata"]["name"],
            "ready": conditions.get("Ready") == "True",
            "version": node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", ""),
            "roles": ",".join(
                key.split("/", 1)[1]
                for key in node["metadata"].get("labels", {})
                if key.startswith("node-role.kubernetes.io/")
            )
            or "worker",
        }
    )

pods = []
for pod in items("pods.json"):
    status = pod.get("status", {})
    container_statuses = status.get("containerStatuses") or []
    ready = sum(1 for c in container_statuses if c.get("ready"))
    restarts = sum(int(c.get("restartCount", 0)) for c in container_statuses)
    waiting = [
        c["state"]["waiting"]["reason"]
        for c in container_statuses
        if c.get("state", {}).get("waiting", {}).get("reason")
    ]
    pods.append(
        {
            "name": pod["metadata"]["name"],
            "phase": status.get("phase", "Unknown"),
            "ready": f"{ready}/{len(container_statuses)}",
            "ready_ok": bool(container_statuses) and ready == len(container_statuses),
            "restarts": restarts,
            "node": pod.get("spec", {}).get("nodeName", ""),
            "images": [c.get("image", "") for c in pod.get("spec", {}).get("containers", [])],
            "waiting": waiting,
            "age": age(pod["metadata"].get("creationTimestamp")),
        }
    )
pods.sort(key=lambda row: row["name"])

deployments = []
for deployment in items("deployments.json"):
    desired = int(deployment.get("spec", {}).get("replicas", 0))
    status = deployment.get("status", {})
    ready = int(status.get("readyReplicas", 0))
    images = [
        c.get("image", "")
        for c in deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    ]
    deployments.append(
        {
            "name": deployment["metadata"]["name"],
            "desired": desired,
            "ready": ready,
            "updated": int(status.get("updatedReplicas", 0)),
            "available": int(status.get("availableReplicas", 0)),
            "ready_ok": ready >= desired,
            "images": images,
            "age": age(deployment["metadata"].get("creationTimestamp")),
        }
    )
deployments.sort(key=lambda row: row["name"])

statefulsets = []
for statefulset in items("statefulsets.json"):
    desired = int(statefulset.get("spec", {}).get("replicas", 0))
    ready = int(statefulset.get("status", {}).get("readyReplicas", 0))
    statefulsets.append(
        {
            "name": statefulset["metadata"]["name"],
            "desired": desired,
            "ready": ready,
            "ready_ok": ready >= desired,
            "age": age(statefulset["metadata"].get("creationTimestamp")),
        }
    )
statefulsets.sort(key=lambda row: row["name"])

jobs = []
for job in items("jobs.json"):
    status = job.get("status", {})
    conditions = {c.get("type"): c.get("status") for c in status.get("conditions", [])}
    jobs.append(
        {
            "name": job["metadata"]["name"],
            "succeeded": int(status.get("succeeded", 0)),
            "failed": int(status.get("failed", 0)),
            "active": int(status.get("active", 0)),
            "complete": conditions.get("Complete") == "True",
            "failed_condition": conditions.get("Failed") == "True",
            "age": age(job["metadata"].get("creationTimestamp")),
        }
    )
jobs.sort(key=lambda row: row["name"])

ingress = []
for resource in items("ingress.json"):
    ingress.append(
        {
            "name": resource["metadata"]["name"],
            "hosts": sorted(
                {
                    rule.get("host", "")
                    for rule in resource.get("spec", {}).get("rules", [])
                    if rule.get("host")
                }
            ),
            "tls": sorted(
                {
                    secret
                    for tls in resource.get("spec", {}).get("tls", [])
                    for secret in [tls.get("secretName", "")]
                    if secret
                }
            ),
            "class": resource.get("spec", {}).get("ingressClassName", ""),
        }
    )
ingress.sort(key=lambda row: row["name"])

hpas = []
for resource in items("hpa.json"):
    hpas.append(
        {
            "name": resource["metadata"]["name"],
            "min": resource.get("spec", {}).get("minReplicas"),
            "max": resource.get("spec", {}).get("maxReplicas"),
            "current": resource.get("status", {}).get("currentReplicas", 0),
            "desired": resource.get("status", {}).get("desiredReplicas", 0),
        }
    )
hpas.sort(key=lambda row: row["name"])

pdbs = []
for resource in items("pdb.json"):
    pdbs.append(
        {
            "name": resource["metadata"]["name"],
            "min_available": resource.get("spec", {}).get("minAvailable"),
            "allowed": resource.get("status", {}).get("disruptionsAllowed", 0),
            "expected": resource.get("status", {}).get("expectedPods", 0),
        }
    )
pdbs.sort(key=lambda row: row["name"])

warnings = []
for event in items("events.json"):
    warnings.append(
        {
            "reason": event.get("reason", ""),
            "object": f"{event.get('involvedObject', {}).get('kind', '')}/{event.get('involvedObject', {}).get('name', '')}",
            "message": (event.get("message", "") or "")[:240],
            "count": int(event.get("count", 1) or 1),
            "last": event.get("lastTimestamp") or event.get("eventTime") or "",
        }
    )
warnings.sort(key=lambda row: row["last"], reverse=True)
warnings = warnings[:10]

bad_pods = [
    pod for pod in pods
    if pod["phase"] not in ("Running", "Succeeded") or (pod["phase"] == "Running" and not pod["ready_ok"])
]
bad_deployments = [row for row in deployments if not row["ready_ok"]]
bad_statefulsets = [row for row in statefulsets if not row["ready_ok"]]
bad_jobs = [row for row in jobs if row["failed_condition"] or (not row["complete"] and row["failed"] > 0 and row["active"] == 0)]
healthy = not (bad_pods or bad_deployments or bad_statefulsets or bad_jobs)

payload = {
    "context": context,
    "namespace": namespace,
    "healthy": healthy,
    "nodes": nodes,
    "deployments": deployments,
    "statefulsets": statefulsets,
    "pods": pods,
    "jobs": jobs,
    "ingress": ingress,
    "hpas": hpas,
    "pdbs": pdbs,
    "warnings": warnings,
}

if as_json:
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0 if healthy or not strict else 1)

print(f"\nContext: {context or '-'}   Namespace: {namespace}")
print("-" * 96)
if nodes:
    for node in nodes:
        state = "Ready" if node["ready"] else "NOT READY"
        print(f"node {node['name']:<32} {node['roles']:<14} {state:<10} {node['version']}")
else:
    print("nodes: none visible to this context")

print(f"\n{'DEPLOYMENT':<24} {'READY':<8} {'UPDATED':<8} {'AGE':<6} IMAGE")
print("-" * 96)
for row in deployments:
    print(
        f"{row['name']:<24} {str(row['ready']) + '/' + str(row['desired']):<8} "
        f"{row['updated']:<8} {row['age']:<6} {', '.join(row['images'])}"
    )
for row in statefulsets:
    print(f"{row['name']:<24} {str(row['ready']) + '/' + str(row['desired']):<8} {'-':<8} {row['age']:<6} statefulset")

print(f"\n{'POD':<44} {'READY':<7} {'RESTARTS':<9} {'AGE':<6} PHASE")
print("-" * 96)
for row in pods:
    waiting = f" [{','.join(row['waiting'])}]" if row["waiting"] else ""
    print(f"{row['name']:<44} {row['ready']:<7} {row['restarts']:<9} {row['age']:<6} {row['phase']}{waiting}")

if jobs:
    print(f"\n{'JOB':<28} {'ACTIVE':<7} {'SUCCEEDED':<10} {'FAILED':<7} {'AGE':<6} STATE")
    print("-" * 96)
    for row in jobs:
        state = "complete" if row["complete"] else ("failed" if row["failed_condition"] else "running")
        print(f"{row['name']:<28} {row['active']:<7} {row['succeeded']:<10} {row['failed']:<7} {row['age']:<6} {state}")

if ingress:
    print(f"\n{'INGRESS':<20} {'CLASS':<10} HOSTS")
    print("-" * 96)
    for row in ingress:
        print(f"{row['name']:<20} {row['class']:<10} {', '.join(row['hosts']) or '-'}")

if hpas:
    print("\nHPA: " + ", ".join(
        f"{row['name']} {row['current']}/{row['desired']} (min {row['min']}, max {row['max']})"
        for row in hpas
    ))
if pdbs:
    print("PDB: " + ", ".join(
        f"{row['name']} allowed {row['allowed']}/{row['expected']}"
        for row in pdbs
    ))

if warnings:
    print("\nRecent warning events:")
    for row in warnings:
        print(f"  {row['reason']:<22} {row['object']:<36} x{row['count']} {row['message']}")
else:
    print("\nNo warning events in the current window.")

print()
if healthy:
    print("Status: healthy (all deployments, statefulsets and pods ready)")
else:
    print("Status: UNHEALTHY")
    if bad_deployments:
        print("  not ready: " + ", ".join(f"{row['name']} ({row['ready']}/{row['desired']})" for row in bad_deployments))
    if bad_statefulsets:
        print("  not ready: " + ", ".join(f"{row['name']} ({row['ready']}/{row['desired']})" for row in bad_statefulsets))
    if bad_pods:
        print("  bad pods: " + ", ".join(row["name"] for row in bad_pods))
    if bad_jobs:
        print("  failed jobs: " + ", ".join(row["name"] for row in bad_jobs))

if strict and not healthy:
    raise SystemExit(1)
PY
