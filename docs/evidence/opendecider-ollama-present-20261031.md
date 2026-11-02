# G-29 OpenDecider availability (host)

| Check | Result |
|---|---|
| `ollama list` contains OpenDecider | Yes — `hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0` |
| Marker file | `data/models/opendecider/OLLAMA_MODEL.txt` |
| `.env` | `DECIDER_BACKEND=ollama`, `DECIDER_MODEL=hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0` |
| Chat shape | Empty `content`; JSON in `message.reasoning` (chat) / `thinking` (generate) — now parsed |
| Optional fallback | `STRANDS_DECIDER_URL` / `DECIDER_BACKEND=strands` |

HF GGUF re-download skipped when Ollama already has the model (`scripts/download_models.sh`).

## Prove — `classify_intent` (2026-10-31 follow-up)

`mcp-decider` parses `message.reasoning` / `thinking` when `content`/`response` is empty, prefers host Ollama when `DECIDER_BACKEND=ollama` (not shadowed by LiteLLM), and uses a longer HTTP timeout for cold Docker→host loads (`DECIDER_HTTP_TIMEOUT_SECONDS`, default 240).

| Probe | Evidence | Engine |
|---|---|---|
| Host `.venv` | [opendecider-ollama-classify-20261031T134008Z.json](./opendecider-ollama-classify-20261031T134008Z.json) | `opendecider_openai_compatible` |
| Live `mcp-decider` | [opendecider-mcp-decider-classify-20261031T135627Z.json](./opendecider-mcp-decider-classify-20261031T135627Z.json) | `opendecider_openai_compatible` |

Earlier keyword-only probes (`…T131233Z`, failed container timeouts) are superseded.

**G-29 status.** Decision-model path proven. Remains **Mitigated** until G-05 WER (closure still pairs speech with decisions). Keyword fallback stays labelled when the model is unreachable.
