#!/usr/bin/env bash
# G-05: call mcp-stt (when up) with real audio, then score with wer_cer.py.
# Does not invent transcripts or silent WAVs. Requires a human reference transcript.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/stt_wer_live.sh --audio <path|url> --reference <text> [options]

  --audio PATH|URL   Local audio file or http(s) URL mcp-stt can fetch
  --reference TEXT   Human reference transcript (required; not invented)
  --language LOCALE  Optional language hint (e.g. en-IN, hi-IN, mr-IN)
  --id CASE_ID       Case id in the run artefact (default: live-1)
  --stt-url URL      mcp-stt base (default: http://127.0.0.1:${MCP_STT_PORT:-5716})
  --out DIR          Evidence directory (default: docs/evidence)

Writes:
  <out>/stt-wer-run-<UTC>.json   actual run (reference + hypothesis)
  <out>/stt-wer-score-<UTC>.json wer_cer.py report

Exits non-zero if mcp-stt is down, audio missing, or transcription fails.
Prefer an http(s) URL the mcp-stt container can fetch; host file:// paths often fail.
EOF
}

AUDIO=""
REFERENCE=""
LANGUAGE=""
CASE_ID="live-1"
STT_URL="${STT_URL:-}"
OUT_DIR="$ROOT/docs/evidence"

while (( $# > 0 )); do
  case "$1" in
    --audio) AUDIO="${2:-}"; shift 2 ;;
    --reference) REFERENCE="${2:-}"; shift 2 ;;
    --language) LANGUAGE="${2:-}"; shift 2 ;;
    --id) CASE_ID="${2:-}"; shift 2 ;;
    --stt-url) STT_URL="${2:-}"; shift 2 ;;
    --out) OUT_DIR="${2:-}"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ -n "$AUDIO" ]] || die "--audio is required"
[[ -n "$REFERENCE" ]] || die "--reference is required (do not invent a transcript)"
require_cmd curl python3
require_env_file

if [[ -z "$STT_URL" ]]; then
  port="$(env_value MCP_STT_PORT 5716)"
  STT_URL="http://127.0.0.1:${port}"
fi
STT_URL="${STT_URL%/}"

if [[ "$AUDIO" =~ ^https?:// ]]; then
  AUDIO_URL="$AUDIO"
else
  [[ -f "$AUDIO" ]] || die "audio file not found: $AUDIO"
  if [[ "$AUDIO" != /* ]]; then
    AUDIO="$(cd "$(dirname "$AUDIO")" && pwd)/$(basename "$AUDIO")"
  fi
  AUDIO_URL="file://${AUDIO}"
  warn "using file:// URL; mcp-stt may not see host paths — prefer http(s)"
fi

step "Probe mcp-stt at $STT_URL"
set +e
health="$(curl -fsS -m 5 "$STT_URL/healthz" 2>/dev/null)"
health_rc=$?
set -e
[[ $health_rc -eq 0 ]] || die "mcp-stt not reachable at $STT_URL/healthz (start core profile first)"
ok "healthz: $health"

secret="$(env_value MCP_CONTEXT_SECRET "")"
[[ -n "$secret" ]] || die "MCP_CONTEXT_SECRET missing in .env"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_json="$OUT_DIR/stt-wer-run-$stamp.json"
score_json="$OUT_DIR/stt-wer-score-$stamp.json"
mkdir -p "$OUT_DIR"

step "Invoke mcp-stt transcribe"
ROOT="$ROOT" TOKEN_AUDIO_URL="$AUDIO_URL" TOKEN_LANG="$LANGUAGE" TOKEN_SECRET="$secret" \
  TOKEN_STT="$STT_URL" TOKEN_REF="$REFERENCE" TOKEN_ID="$CASE_ID" \
  TOKEN_RUN="$run_json" python3 - <<'PY'
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path[:0] = [str(root / "packages" / "py-common")]
from sahyog_common.context import ExecutionContext, Role, sign_context

secret = os.environ["TOKEN_SECRET"]
now = int(time.time())
ctx = ExecutionContext(
    actor_subject="stt-wer-live",
    actor_role=Role.SERVICE,
    trace_id=uuid.uuid4().hex[:32],
    issued_at=now,
    expires_at=now + 90,
)
token = sign_context(ctx, secret)
body: dict = {"audio_url": os.environ["TOKEN_AUDIO_URL"]}
lang = (os.environ.get("TOKEN_LANG") or "").strip()
if lang:
    body["language"] = lang
req = urllib.request.Request(
    os.environ["TOKEN_STT"].rstrip("/") + "/tools/transcribe",
    data=json.dumps(body).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "X-Sahyog-Context": token,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")[:500]
    print(json.dumps({"status": "invoke_failed", "http": exc.code, "body": detail}), file=sys.stderr)
    raise SystemExit(2) from exc
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"status": "invoke_failed", "error": str(exc)}), file=sys.stderr)
    raise SystemExit(2) from exc

# MCP envelope is {tool, service, result:{status, transcript, ...}} (or flat result).
result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
status = result.get("status")
hypothesis = (result.get("transcript") or "").strip()
if status != "ok" or not hypothesis:
    out = {
        "status": "stt_failed",
        "mcp_response": payload,
        "note": "No hypothesis produced; G-05 remains unmeasured.",
    }
    Path(os.environ["TOKEN_RUN"]).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    raise SystemExit(2)

run = {
    "synthetic": False,
    "source": "scripts/stt_wer_live.sh",
    "mcp_status": status,
    "engine": result.get("engine"),
    "adapter": result.get("adapter"),
    "audio_url": os.environ["TOKEN_AUDIO_URL"],
    "cases": [
        {
            "id": os.environ["TOKEN_ID"],
            "reference": os.environ["TOKEN_REF"],
            "hypothesis": hypothesis,
            "modality": "stt",
            "language": result.get("language") or lang or None,
        }
    ],
}
Path(os.environ["TOKEN_RUN"]).write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"wrote": os.environ["TOKEN_RUN"], "hypothesis_len": len(hypothesis)}, indent=2))
PY

step "Score with wer_cer.py"
uv run python "$ROOT/evals/harness/wer_cer.py" --run "$run_json" --out "$score_json"
ok "run=$run_json"
ok "score=$score_json"
