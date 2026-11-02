# G-05 STT / WER status

Recorded: `2026-10-31T17:02:48Z` (local operator pass).

## Status: **Mitigated** (English public LibriSpeech measured; hi/mr + OCR residual)

| Check | Result |
|---|---|
| faster-whisper weights on disk | Present: `data/models/whisper/faster-whisper-small/` |
| Public non-PHI EN fixtures | LibriSpeech clean excerpts under `evals/fixtures/public_human/` (not TTS; `synthetic:false`) |
| Live transcription + `wer_cer.py --run` | **Measured** — mcp-stt hypotheses scored against public references |
| Aggregate EN WER (normalised case/punct) | **0.0** on 3 clips — [stt-wer-score-aggregate-20261031T170248Z.json](./stt-wer-score-aggregate-20261031T170248Z.json) |
| Invented hypotheses / authored WER | **Refused** (`synthetic:true` rejected by harness) |

## Evidence artefacts

| Artefact | Role |
|---|---|
| [stt-wer-run-aggregate-20261031T170248Z.json](./stt-wer-run-aggregate-20261031T170248Z.json) | Live mcp-stt run (`synthetic:false`) |
| [stt-wer-score-aggregate-20261031T170248Z.json](./stt-wer-score-aggregate-20261031T170248Z.json) | `wer_cer.py` scores (`status=measured`, `mean=0.0`) |
| Per-clip run/score `stt-wer-{run,score}-20261031T17024{4,5,6}Z.json` | Individual LibriSpeech cases |

`evals/harness/wer_cer.py` lowercases and strips punctuation before edit distance
(standard ASR practice). Raw hypotheses retain casing from Whisper.

## Residual (keeps gap Mitigated, not Closed)

- Hindi / Marathi / code-mixed clinical speech not measured on this pass.
- Devanagari OCR CER not measured.
- Do not present automated transcription as a validated clinical record.
- TTS pangram under `evals/fixtures/non_phi/` remains `wer_evidence: false` (smoke only).

## How to re-run

```bash
scripts/stt_wer_live.sh   # against live mcp-stt + public_human fixtures
uv run python evals/harness/wer_cer.py --run docs/evidence/stt-wer-run-….json --out …
```
