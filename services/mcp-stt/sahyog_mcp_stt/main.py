"""Speech-to-text via local faster-whisper or optional cloud transcription.

Local weights load from WHISPER_MODEL_DIR / STT_MODEL_PATH. Cloud mode requires
ALLOW_CLOUD_STT=true and STT_ADAPTER=cloud plus STT_CLOUD_BASE_URL / API key.
Cloud is fail-closed when the feature flag or credentials are missing — never
invent a transcript. Cloud is for approved egress only (G-19/G-28).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from sahyog_common.context import ExecutionContext
from sahyog_common.mcp_service import create_mcp_app

_MODEL = None
_MODEL_ERROR: str | None = None


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _adapter() -> str:
    return (os.environ.get("STT_ADAPTER") or "local").strip().lower()


def _cloud_allowed() -> bool:
    return _truthy(os.environ.get("ALLOW_CLOUD_STT"))


def _model_path() -> Path | None:
    for key in ("WHISPER_MODEL_DIR", "STT_MODEL_PATH", "WHISPER_MODEL"):
        raw = os.environ.get(key, "").strip()
        if raw:
            path = Path(raw)
            if path.exists():
                return path
    default = Path("/models/whisper/faster-whisper-small")
    return default if default.exists() else None


def _load_model() -> Any:
    global _MODEL, _MODEL_ERROR
    if _MODEL is not None:
        return _MODEL
    if _MODEL_ERROR:
        raise RuntimeError(_MODEL_ERROR)
    path = _model_path()
    if path is None:
        _MODEL_ERROR = "whisper_weights_missing"
        raise RuntimeError(_MODEL_ERROR)
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        _MODEL_ERROR = "faster_whisper_not_installed"
        raise RuntimeError(_MODEL_ERROR) from exc
    device = os.environ.get("WHISPER_DEVICE", os.environ.get("STT_DEVICE", "cpu"))
    compute = os.environ.get("WHISPER_COMPUTE_TYPE", os.environ.get("STT_COMPUTE_TYPE", "int8"))
    _MODEL = WhisperModel(str(path), device=device, compute_type=compute)
    return _MODEL


async def _fetch_audio(url: str) -> Path:
    suffix = Path(url.split("?", 1)[0]).suffix or ".wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    tmp.close()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        tmp_path.write_bytes(response.content)
    return tmp_path


def _turn(start_s: float, end_s: float, text: str) -> dict[str, Any]:
    """One transcript segment in the scribe contract (see apps/api scribe service).

    scribe reads `start_ms`/`end_ms`/`speaker`/`text`; the original float-second
    `start`/`end` are kept for existing clients. Whisper does not diarise, so the
    speaker is always "other" rather than a guessed doctor/patient label.
    """
    return {
        "speaker": "other",
        "start_ms": max(0, int(round(start_s * 1000))),
        "end_ms": max(0, int(round(end_s * 1000))),
        "start": start_s,
        "end": end_s,
        "text": text,
    }


def _duration_ms(turns: list[dict[str, Any]], info_duration: Any) -> int:
    try:
        if info_duration is not None and float(info_duration) > 0:
            return int(round(float(info_duration) * 1000))
    except (TypeError, ValueError):
        pass
    return max((int(t.get("end_ms", 0)) for t in turns), default=0)


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "stt_unavailable",
        "reason": reason,
        "transcript": None,
        "turns": [],
    }


def _patch_av_open_compat() -> None:
    """faster-whisper passes metadata_errors= to av.open; some PyAV builds reject it."""
    try:
        import av
    except ImportError:
        return
    if getattr(av.open, "_sahyog_compat", False):
        return
    original = av.open

    def open_compat(*args: Any, **kwargs: Any):  # noqa: ANN401
        kwargs.pop("metadata_errors", None)
        return original(*args, **kwargs)

    open_compat._sahyog_compat = True  # type: ignore[attr-defined]
    av.open = open_compat  # type: ignore[assignment]


async def _transcribe_local(audio_url: str, language: Any) -> dict[str, Any]:
    try:
        model = _load_model()
    except RuntimeError as exc:
        return _unavailable(str(exc))
    path: Path | None = None
    try:
        _patch_av_open_compat()
        path = await _fetch_audio(audio_url.strip())
        lang = None
        if isinstance(language, str) and language.strip():
            lang = language.strip().split("-")[0]
        segments, info = model.transcribe(str(path), language=lang, vad_filter=True)
        turns = []
        texts = []
        for segment in segments:
            text = (segment.text or "").strip()
            if not text:
                continue
            texts.append(text)
            turns.append(_turn(float(segment.start), float(segment.end), text))
        return {
            "status": "ok",
            "engine": "faster-whisper",
            "adapter": "local",
            "language": getattr(info, "language", lang),
            "transcript": " ".join(texts).strip(),
            "turns": turns,
            "duration_ms": _duration_ms(turns, getattr(info, "duration", None)),
        }
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"transcribe_failed:{exc}")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def _transcribe_cloud(audio_url: str, language: Any) -> dict[str, Any]:
    if not _cloud_allowed():
        return _unavailable("cloud_stt_disabled")
    base = (os.environ.get("STT_CLOUD_BASE_URL") or "").rstrip("/")
    api_key = (os.environ.get("STT_CLOUD_API_KEY") or "").strip()
    model = (os.environ.get("STT_CLOUD_MODEL") or "whisper-1").strip()
    if not base or not api_key:
        return _unavailable("cloud_stt_unconfigured")
    path: Path | None = None
    try:
        path = await _fetch_audio(audio_url.strip())
        headers = {"Authorization": f"Bearer {api_key}"}
        data: dict[str, str] = {"model": model}
        if isinstance(language, str) and language.strip():
            data["language"] = language.strip().split("-")[0]
        timeout = float(os.environ.get("STT_CLOUD_TIMEOUT_SECONDS") or "60")
        async with httpx.AsyncClient(timeout=timeout) as client:
            with path.open("rb") as handle:
                response = await client.post(
                    f"{base}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files={"file": (path.name, handle, "application/octet-stream")},
                )
        if response.status_code >= 400:
            return _unavailable(f"cloud_stt_http_{response.status_code}")
        payload = response.json()
        text = str(payload.get("text") or "").strip()
        if not text:
            return _unavailable("cloud_stt_empty")
        return {
            "status": "ok",
            "engine": "cloud_whisper_compat",
            "adapter": "cloud",
            "model": model,
            "language": data.get("language"),
            "transcript": text,
            "turns": [_turn(0.0, 0.0, text)],
            "duration_ms": 0,
        }
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"cloud_stt_failed:{exc}")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


async def transcribe(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    audio_url = args.get("audio_url") or args.get("url")
    language = args.get("language") or args.get("locale")
    if not isinstance(audio_url, str) or not audio_url.strip():
        raise ValueError("audio_url is required")
    adapter = _adapter()
    if adapter == "cloud":
        result = await _transcribe_cloud(audio_url, language)
    elif adapter in {"local", "mcp", "faster-whisper", ""}:
        result = await _transcribe_local(audio_url, language)
    else:
        result = _unavailable(f"unknown_stt_adapter:{adapter}")
    result["trace_id"] = context.trace_id
    return result


async def get_transcript(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    """Alias for clients that poll a job id — this build is sync, so re-run transcribe."""
    return await transcribe(args, context)


async def stt_status(_args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    adapter = _adapter()
    cloud = adapter == "cloud"
    local_ready = _model_path() is not None
    return {
        "adapter": adapter,
        "cloud_allowed": _cloud_allowed(),
        "local_weights_present": local_ready,
        "ready": (_cloud_allowed() and bool(os.environ.get("STT_CLOUD_BASE_URL")))
        if cloud
        else local_ready,
        "trace_id": context.trace_id,
    }


app = create_mcp_app(
    "stt",
    {
        "transcribe": (transcribe, "Transcribe audio from an internal URL"),
        "get_transcript": (get_transcript, "Fetch transcript (sync alias of transcribe)"),
        "stt_status": (stt_status, "Report local/cloud STT readiness without inventing audio"),
    },
)
