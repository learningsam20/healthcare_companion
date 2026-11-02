#!/usr/bin/env bash
# Download local specialty models into data/models (gitignored).
# Chat/embed models stay on Ollama; this script covers Whisper, GLiNER-PII, spaCy, OpenDecider GGUF.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${MODELS_DIR:-$ROOT/data/models}"
mkdir -p "$MODELS_DIR"/{whisper,gliner-pii,spacy,opendecider}

echo "==> Models directory: $MODELS_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

python3 - <<'PY'
import os
import sys
from pathlib import Path

models = Path(os.environ.get("MODELS_DIR", "data/models")).resolve()
models.mkdir(parents=True, exist_ok=True)

def ensure_pkg(name: str) -> None:
    try:
        __import__(name.split(".")[0].replace("-", "_") if False else name)
    except Exception:
        pass

# huggingface_hub is enough for most pulls
try:
    from huggingface_hub import hf_hub_download, snapshot_download
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"])
    from huggingface_hub import hf_hub_download, snapshot_download

whisper_dir = models / "whisper" / "faster-whisper-small"
if not any(whisper_dir.glob("*")):
    print("Downloading faster-whisper-small…")
    snapshot_download(
        repo_id="Systran/faster-whisper-small",
        local_dir=str(whisper_dir),
    )
else:
    print("faster-whisper-small already present")

gliner_dir = models / "gliner-pii" / "gliner-pii-large-v1.0"
if not any(gliner_dir.glob("*")):
    print("Downloading GLiNER-PII…")
    snapshot_download(
        repo_id="knowledgator/gliner-pii-large-v1.0",
        local_dir=str(gliner_dir),
    )
else:
    print("GLiNER-PII already present")

# Decision models — prefer light Ollama Jev (tev1:0.8b) + small HF Q4 GGUF; avoid Q8_0 (~4.3GB).
od_dir = models / "opendecider"
marker = od_dir / "model.gguf"
q4_name = "opendecider-small-td-q4_k_m.gguf"
q4_path = od_dir / q4_name
jev_model = os.environ.get("DECIDER_MODEL", "tev1:0.8b").strip() or "tev1:0.8b"
import shutil
import subprocess

def ollama_has(name: str) -> bool:
    try:
        out = subprocess.check_output(["ollama", "list"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    return name in out or name.split(":")[0] in out

def ollama_pull(name: str) -> None:
    print(f"Pulling Ollama decision model {name}…")
    subprocess.check_call(["ollama", "pull", name])

# Always prefer a light Jev model for /v1/systemone (not nimble:9b ~9.5GB).
if not ollama_has(jev_model):
    try:
        ollama_pull(jev_model)
    except Exception as exc:
        print(f"warning: could not pull {jev_model}: {exc}")
else:
    print(f"Ollama decision model present: {jev_model}")
(od_dir / "OLLAMA_MODEL.txt").write_text(jev_model + "\n", encoding="utf-8")

if q4_path.exists() and not marker.exists():
    marker.symlink_to(q4_name)
    print(f"Linked {marker.name} -> {q4_name}")
elif marker.exists():
    print("OpenDecider GGUF already present")
elif os.environ.get("DOWNLOAD_OPENDECIDER_GGUF", "1").lower() in {"1", "true", "yes"}:
    print("Downloading OpenDecider Q4 GGUF (small HF file)…")
    preferred = (
        "opendecider-small-td-q4_k_m.gguf",
        "opendecider-small-q4_k_m.gguf",
        "opendecider-small-td-q8_0.gguf",
        "opendecider-small-q8_0.gguf",
    )
    path = None
    for filename in preferred:
        try:
            path = hf_hub_download(
                repo_id="manjunathshiva/opendecider-small-td-GGUF",
                filename=filename,
                local_dir=str(od_dir),
            )
            break
        except Exception:
            continue
    if path is None:
        snapshot_download(
            repo_id="manjunathshiva/opendecider-small-td-GGUF",
            local_dir=str(od_dir / "repo"),
            allow_patterns=["*.gguf", "*.md", "*.json"],
        )
        ggufs = sorted((od_dir / "repo").rglob("*.gguf"), key=lambda p: p.stat().st_size)
        if not ggufs:
            raise SystemExit("No OpenDecider GGUF found in HuggingFace repo")
        path = str(ggufs[0])
    target = od_dir / "model.gguf"
    if Path(path).resolve() != target.resolve():
        shutil.copy2(path, target)
    print(f"OpenDecider ready at {target}")
else:
    print(
        "OpenDecider Q4 GGUF absent. Prefer: `ollama pull tev1:0.8b` for Jev decisions, "
        "or DOWNLOAD_OPENDECIDER_GGUF=1 for opendecider-small-td-q4_k_m.gguf (llama.cpp). "
        "Avoid the 4.3GB Q8_0 Ollama tag on P hosts."
    )

# spaCy English model for Presidio
spacy_dir = models / "spacy"
try:
    import spacy
    from spacy.cli import download as spacy_download
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "spacy"])
    from spacy.cli import download as spacy_download

print("Ensuring spaCy en_core_web_sm…")
try:
    import en_core_web_sm  # type: ignore
except Exception:
    spacy_download("en_core_web_sm")

# Write a small manifest for MCP services
manifest = models / "manifest.json"
manifest.write_text(
    __import__("json").dumps(
        {
            "whisper": str(whisper_dir),
            "gliner_pii": str(gliner_dir),
            "opendecider_gguf": str(od_dir / "model.gguf"),
            "spacy": "en_core_web_sm",
        },
        indent=2,
    )
    + "\n"
)
print(f"Wrote {manifest}")
print("Done.")
PY

echo "==> Next: set env paths (see .env.example) and rebuild mcp-stt / mcp-pii / llama-decider"
