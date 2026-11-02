# G-28 composite PII blocker (2026-10-31) — superseded

**Status:** Resolved / superseded by [pii-composite-prove-20261031.md](./pii-composite-prove-20261031.md).

The `regex_fallback` / missing-deps condition below was the pre-rebuild state. After image `sahyog-api:local` (CPU torch 2.5.1 + `en_core_web_sm` + GLiNER) and `mcp-pii` recreate, detect reports `engine=composite`, `not_clinical_grade=false`, count=3 — see [mcp-pii-detect-probe.json](./mcp-pii-detect-probe.json). Keep `EXTERNAL_EGRESS_ENABLED=false` until security sign-off (G-28 residual / G-19).

---

## Historical record (pre-prove)

| Check | Result |
|---|---|
| Host weights `data/models/gliner-pii` | Present (~657M+; download may still finish) |
| Host weights `data/models/whisper` | Present (~464M) |
| Compose mount `./data/models:/models:ro` | OK |
| `GLINER_MODEL` in container | `/models/gliner-pii/gliner-pii-large-v1.0` |
| Detect `engine` | **`regex_fallback`** (`not_clinical_grade=true`) |
| Root cause | Image `/opt/venv` missing `gliner`, `presidio_analyzer`, `spacy` (`ModuleNotFoundError`) despite workspace pyproject deps — last full `docker compose build api` hung/OOM during `uv sync` |
| Egress | Kept `EXTERNAL_EGRESS_ENABLED=false` |

## Next (completed)

```bash
# When Docker has memory headroom:
docker compose build api
docker compose --profile minimal up -d --force-recreate mcp-pii
# Expect engine=composite on signed /tools/detect
```
