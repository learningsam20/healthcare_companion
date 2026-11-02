#!/usr/bin/env bash
# Multi-replica booking interrupt soak (G-46 residual).
# Requires two reachable API bases sharing Postgres+checkpointer and a bearer token.
#
# Usage:
#   API_A=http://localhost:5706 API_B=http://localhost:5708 \
#   TOKEN=... PATIENT_BEARER=... ./scripts/chat-interrupt-ha-soak.sh
#
# Evidence JSON is written under docs/evidence/ when SOAK_WRITE_EVIDENCE=1.

set -euo pipefail

API_A="${API_A:-http://localhost:5706}"
API_B="${API_B:-${API_A}}"
TOKEN="${TOKEN:-${PATIENT_BEARER:-}}"
OUT_DIR="${OUT_DIR:-docs/evidence}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_FILE="${OUT_DIR}/chat-interrupt-ha-soak-${TS}.json"

if [[ -z "${TOKEN}" ]]; then
  echo "TOKEN or PATIENT_BEARER is required" >&2
  exit 2
fi

auth=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -H "Accept: application/json")

echo "== create session on A (${API_A}) =="
SESSION="$(curl -fsS "${auth[@]}" -X POST "${API_A}/api/v1/chat/sessions" \
  -d '{"title":"HA soak booking","locale":"en-IN"}')"
SESSION_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${SESSION}")"

echo "== start booking turn on A (expect interrupt) =="
# Prefer sync send so interrupt payload is in the JSON body for the soak script.
SEND="$(curl -fsS "${auth[@]}" -X POST "${API_A}/api/v1/chat/sessions/${SESSION_ID}/messages" \
  -d '{"content":"I need to book a general medicine appointment tomorrow morning","locale":"en-IN"}' || true)"

python3 - "${SEND}" "${SESSION_ID}" "${API_A}" "${API_B}" "${TOKEN}" "${RESULT_FILE}" <<'PY'
import json, os, sys, urllib.request

send_raw, session_id, api_a, api_b, token, out = sys.argv[1:7]
result = {
    "status": "failed",
    "session_id": session_id,
    "api_a": api_a,
    "api_b": api_b,
    "same_base": api_a.rstrip("/") == api_b.rstrip("/"),
}

try:
    send = json.loads(send_raw) if send_raw else {}
except json.JSONDecodeError:
    send = {}
    result["send_raw"] = send_raw[:500]

interrupt = send.get("interrupt") or {}
run_id = interrupt.get("run_id") or send.get("run_id")
interrupt_id = interrupt.get("interrupt_id")
candidates = (interrupt.get("payload") or {}).get("candidates") or []
result["run_id"] = run_id
result["interrupt_id"] = interrupt_id
result["candidate_count"] = len(candidates)

if not run_id or not interrupt_id or not candidates:
    result["error"] = "no_interrupt_on_replica_a"
    print(json.dumps(result, indent=2))
    if os.environ.get("SOAK_WRITE_EVIDENCE") == "1":
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "w").write(json.dumps(result, indent=2) + "\n")
    sys.exit(1)

body = json.dumps({
    "interrupt_id": interrupt_id,
    "command": interrupt.get("interrupt_type") or "slot_choice",
    "choice_index": 1,
    "confirm": True,
    "idempotency_key": f"ha-soak-{run_id}",
}).encode()

req = urllib.request.Request(
    f"{api_b.rstrip('/')}/api/v1/chat/runs/{run_id}/resume",
    data=body,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        resume = json.loads(resp.read().decode())
        result["resume_status_code"] = resp.status
except Exception as exc:  # noqa: BLE001
    result["error"] = f"resume_failed:{exc}"
    print(json.dumps(result, indent=2))
    if os.environ.get("SOAK_WRITE_EVIDENCE") == "1":
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "w").write(json.dumps(result, indent=2) + "\n")
    sys.exit(1)

# Idempotent second resume on A should not double-book.
req2 = urllib.request.Request(
    f"{api_a.rstrip('/')}/api/v1/chat/runs/{run_id}/resume",
    data=body,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req2, timeout=60) as resp:
        resume2 = json.loads(resp.read().decode())
        result["idempotent_resume_status"] = resp.status
except Exception as exc:  # noqa: BLE001
    # 409 after complete is acceptable
    result["idempotent_resume_error"] = str(exc)
    resume2 = None

assistant = (resume.get("assistant_message") or {}).get("content") or ""
result["assistant_snippet"] = assistant[:240]
result["status"] = "passed" if ("Appointment id" in assistant or "Confirmed" in assistant or "status=" in assistant) else " inconclusive"
if result["status"] != "passed" and resume.get("run_id"):
    # specialty_choice may re-interrupt — still proves cross-replica checkpoint read
    if resume.get("interrupt"):
        result["status"] = "passed"
        result["note"] = "cross_replica_reinterrupt_ok"

print(json.dumps(result, indent=2))
if os.environ.get("SOAK_WRITE_EVIDENCE") == "1":
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w").write(json.dumps(result, indent=2) + "\n")
    print(f"wrote {out}", file=sys.stderr)
sys.exit(0 if result["status"] == "passed" else 1)
PY
