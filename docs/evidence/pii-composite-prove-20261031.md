# G-28 composite PII prove (2026-10-31)

| Check | Result |
|---|---|
| Image | `sahyog-api:local` (CPU torch 2.5.1 + `en_core_web_sm` + GLiNER wheels) |
| `torch.cuda.is_available()` | `False` |
| Detect `engine` | **`composite`** |
| HTTP | 200 |
| Elapsed | 7.8s |
| Evidence | [mcp-pii-detect-probe.json](./mcp-pii-detect-probe.json) |
| Egress | Keep `EXTERNAL_EGRESS_ENABLED=false` until security sign-off |
