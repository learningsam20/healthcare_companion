"""mcp-stt output must satisfy what the scribe service reads (G-05 contract)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sahyog_mcp_stt import main as stt


class _FakeModel:
    def transcribe(self, _path: str, language=None, vad_filter=True):  # noqa: ANN001
        segments = [
            SimpleNamespace(start=0.0, end=1.25, text=" The quick brown fox "),
            SimpleNamespace(start=1.25, end=2.5, text=""),
            SimpleNamespace(start=1.25, end=2.67, text="jumps over the lazy dog."),
        ]
        return iter(segments), SimpleNamespace(language="en", duration=2.67)


@pytest.mark.asyncio
async def test_local_turns_match_scribe_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt, "_load_model", lambda: _FakeModel())

    async def fake_fetch(_url: str) -> Path:
        return Path("/nonexistent-but-unlinked.wav")

    monkeypatch.setattr(stt, "_fetch_audio", fake_fetch)
    result = await stt._transcribe_local("http://stt-fixture/x.wav", "en-US")
    assert result["status"] == "ok"
    assert result["duration_ms"] == 2670
    assert [t["text"] for t in result["turns"]] == [
        "The quick brown fox",
        "jumps over the lazy dog.",
    ]
    first = result["turns"][0]
    assert first["speaker"] == "other"  # no diarisation: never guess doctor/patient
    assert (first["start_ms"], first["end_ms"]) == (0, 1250)
    assert first["start"] == 0.0 and first["end"] == 1.25  # legacy seconds kept


@pytest.mark.asyncio
async def test_transcribe_requires_audio_url() -> None:
    from sahyog_common.context import ExecutionContext

    ctx = ExecutionContext.model_construct(trace_id="t")  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="audio_url"):
        await stt.transcribe({"object_key": "audio/x.wav"}, ctx)


def test_non_phi_fixture_manifest_is_honest() -> None:
    import json

    root = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "non_phi"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True and manifest["wer_evidence"] is False
    for item in manifest["files"]:
        assert item["phi"] is False
        assert (root / item["audio"]).is_file()
        assert (root / item["reference"]).read_text(encoding="utf-8").strip()
        assert item["provenance"]["kind"]
