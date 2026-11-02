#!/usr/bin/env bash
# Cap host Ollama physical memory for the Sahyog pilot (G-49).
# Sets daemon defaults so KV cache stays within ~16 GiB RSS budget.
# Virtual address space may still be large on macOS; that is expected.
set -euo pipefail

CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH_CAP:-8192}"
MAX_LOADED="${OLLAMA_MAX_LOADED_MODELS_CAP:-1}"
NUM_PARALLEL="${OLLAMA_NUM_PARALLEL_CAP:-1}"
KEEP_ALIVE="${OLLAMA_KEEP_ALIVE_CAP:-5m}"

PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST="${PLIST_DIR}/com.sahyog.ollama-env.plist"
mkdir -p "${PLIST_DIR}"

cat >"${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.sahyog.ollama-env</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>
launchctl setenv OLLAMA_CONTEXT_LENGTH ${CONTEXT_LENGTH};
launchctl setenv OLLAMA_MAX_LOADED_MODELS ${MAX_LOADED};
launchctl setenv OLLAMA_NUM_PARALLEL ${NUM_PARALLEL};
launchctl setenv OLLAMA_KEEP_ALIVE ${KEEP_ALIVE};
    </string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
EOF

launchctl unload "${PLIST}" 2>/dev/null || true
launchctl load "${PLIST}"
launchctl setenv OLLAMA_CONTEXT_LENGTH "${CONTEXT_LENGTH}"
launchctl setenv OLLAMA_MAX_LOADED_MODELS "${MAX_LOADED}"
launchctl setenv OLLAMA_NUM_PARALLEL "${NUM_PARALLEL}"
launchctl setenv OLLAMA_KEEP_ALIVE "${KEEP_ALIVE}"

echo "Ollama env capped: CONTEXT_LENGTH=${CONTEXT_LENGTH} MAX_LOADED=${MAX_LOADED} NUM_PARALLEL=${NUM_PARALLEL} KEEP_ALIVE=${KEEP_ALIVE}"
echo "Quit and reopen the Ollama app (or: killall Ollama; open -a Ollama) so the daemon picks these up."
echo "Also set Context length ≤ ${CONTEXT_LENGTH} in Ollama Desktop Settings if the slider is higher."
echo "Verify after restart: ollama ps  (CONTEXT column should be ≤ ${CONTEXT_LENGTH})"
