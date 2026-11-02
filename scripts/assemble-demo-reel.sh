#!/usr/bin/env bash
# Capture continuous workflow demos (slicer→live nav) + intro slides, narrate, assemble 6–7 min MP4.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT_DIR="$ROOT/docs/evidence/demo-recording"
CLIPS_DIR="$OUT_DIR/clips"
AUDIO_DIR="$OUT_DIR/audio"
SEG_DIR="$OUT_DIR/segments"
mkdir -p "$OUT_DIR" "$CLIPS_DIR" "$AUDIO_DIR" "$SEG_DIR"

export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://localhost:5729}"
export DEMO_REEL=1
export DEMO_REEL_RESUME="${DEMO_REEL_RESUME:-0}"
VOICE="${DEMO_VOICE:-Aman}"
RATE="${DEMO_SAY_RATE:-168}"

# Grafana login for telemetry chapter (avoid `source .env`, which can hang on special chars).
if [[ -z "${GRAFANA_ADMIN_PASSWORD:-}" && -f "$ROOT/.env" ]]; then
  GRAFANA_ADMIN_PASSWORD="$(
    awk -F= '/^GRAFANA_ADMIN_PASSWORD=/{sub(/^GRAFANA_ADMIN_PASSWORD=/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$ROOT/.env"
  )"
  export GRAFANA_ADMIN_PASSWORD
fi

echo "==> Chaptered demo reel against $PLAYWRIGHT_BASE_URL (voice=$VOICE resume=$DEMO_REEL_RESUME)"

if [[ "${SKIP_CAPTURE:-0}" != "1" ]]; then
  (
    cd apps/web
    npx playwright test auth.setup.ts --project=setup
    DEMO_REEL=1 DEMO_REEL_RESUME="$DEMO_REEL_RESUME" \
      GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}" \
      npx playwright test demo-reel.spec.ts --project=chromium-desktop-light
  )
fi

MANIFEST="$OUT_DIR/manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "Missing $MANIFEST — run capture first" >&2
  exit 1
fi

python3 - <<'PY' "$MANIFEST" "$CLIPS_DIR" "$AUDIO_DIR" "$SEG_DIR" "$VOICE" "$RATE" "$OUT_DIR"
import json, subprocess, sys, wave, contextlib
from pathlib import Path

manifest_path, clips_dir, audio_dir, seg_dir, voice, rate, out_dir = map(Path, sys.argv[1:])
chapters = json.loads(manifest_path.read_text())["chapters"]

def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)

def aiff_to_wav(aiff: Path, wav: Path):
    run(["ffmpeg", "-y", "-i", str(aiff), "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", str(wav)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wav_duration(path: Path) -> float:
    with contextlib.closing(wave.open(str(path), "rb")) as w:
        return w.getnframes() / float(w.getframerate())

def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    ).strip()
    return float(out)

concat_list = seg_dir / "concat.txt"
chapters_ff = out_dir / "chapters.ffmetadata"
lines = [";FFMETADATA1", "title=Sahyog Care Companion — product reel"]
concat_entries = []
t = 0.0
meta = []

for ch in chapters:
    clip = clips_dir / ch["file"]
    if not clip.exists():
        raise SystemExit(f"missing clip {clip}")
    stem = ch["id"]
    kind = ch["kind"]
    aiff = audio_dir / f"{stem}.aiff"
    wav = audio_dir / f"{stem}.wav"
    script = audio_dir / f"{stem}.txt"
    script.write_text(ch["narration"] + "\n")
    run(["say", "-v", voice, "-r", rate, "-o", str(aiff), "-f", str(script)])
    aiff_to_wav(aiff, wav)
    audio_len = wav_duration(wav)
    video_len = probe_duration(clip)

    # Workflow chapters: keep live navigation. Condense only extreme scribe waits.
    # Allow a short post-VO beat (watching UI) but never minutes of silence.
    is_workflow = kind in {"workflow", "live"}
    if is_workflow and video_len > 120 and "e5" in stem:
        # Keep walk-in + transcript head, then sign + clinical-notes tail.
        head, mid_skip_tail = 65.0, 70.0
        condensed = seg_dir / f"{stem}-condensed.mp4"
        run([
            "ffmpeg", "-y", "-i", str(clip),
            "-filter_complex",
            f"[0:v]trim=0:{head},setpts=PTS-STARTPTS[v0];"
            f"[0:v]trim=start={max(head, video_len - mid_skip_tail)},setpts=PTS-STARTPTS[v1];"
            f"[v0][v1]concat=n=2:v=1:a=0,scale=1440:900:force_original_aspect_ratio=decrease,"
            "pad=1440:900:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v]",
            "-map", "[v]", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
            str(condensed),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clip = condensed
        video_len = probe_duration(clip)

    if is_workflow:
        post_vo = 18.0 if "e5" in stem else 6.0
        target = max(audio_len + 0.8, min(video_len, audio_len + post_vo))
        # Prefer keeping the full live take when it is already a short professional beat.
        if "e5" in stem:
            # Never cut the signed-note / clinical-notes ending off a condensed E5 take.
            target = video_len
        elif video_len <= 45 and video_len > audio_len:
            target = video_len
        elif video_len > audio_len + post_vo and video_len <= 130:
            target = min(video_len, max(audio_len + post_vo, video_len * 0.92))
    else:
        target = max(audio_len + 0.5, video_len)

    seg = seg_dir / f"{stem}.mp4"
    # Soft fade narration in; pad silence only when VO outlasts video.
    filter_v = (
        "scale=1440:900:force_original_aspect_ratio=decrease,"
        "pad=1440:900:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
        f"tpad=stop_mode=clone:stop_duration={max(0.0, target - video_len):.3f}"
    )
    run([
        "ffmpeg", "-y",
        "-i", str(clip),
        "-i", str(wav),
        "-filter_complex",
        f"[0:v]{filter_v}[v];[1:a]afade=t=in:st=0:d=0.25,apad=whole_dur={target:.3f}[a]",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{target:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(seg),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    start_ms = int(t * 1000)
    end_ms = int((t + target) * 1000)
    lines += [
        "",
        "[CHAPTER]",
        "TIMEBASE=1/1000",
        f"START={start_ms}",
        f"END={end_ms}",
        f"title={ch['id']} ({kind})",
    ]
    meta.append({"id": ch["id"], "kind": kind, "start": round(t, 2), "duration": round(target, 2)})
    concat_entries.append(f"file '{seg}'")
    t += target

chapters_ff.write_text("\n".join(lines) + "\n")
concat_list.write_text("\n".join(concat_entries) + "\n")
(out_dir / "timeline.json").write_text(json.dumps({"total_seconds": round(t, 2), "chapters": meta}, indent=2))

stitched = out_dir / "sahyog-demo-reel-raw.mp4"
final = out_dir / "sahyog-demo-6min.mp4"
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(stitched)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
run([
    "ffmpeg", "-y", "-i", str(stitched), "-i", str(chapters_ff),
    "-map_metadata", "1", "-codec", "copy", str(final),
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

print(f"Total duration ≈ {t:.1f}s ({t/60:.1f} min)")
print(f"Canonical recording: {final}")
print(json.dumps({"total_seconds": round(t, 2), "chapters": len(meta)}, indent=2))
PY

ls -lh "$OUT_DIR/sahyog-demo-6min.mp4"
echo "Canonical recording: docs/evidence/demo-recording/sahyog-demo-6min.mp4"
