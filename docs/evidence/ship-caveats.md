# Ship caveats (pilot-ready)

Authoritative gap detail remains in [gaps.md](../gaps.md) **v1.16**. This page is the short list of **known caveats against requirements/design** for a supervised pilot ship after the 2026-11-01 notify/vault/residual pass.

## Must-know before go-live

| Caveat | Gap | Why it remains |
|---|---|---|
| Not a medical device / no CDSCO–FDA clearance | G-12 | Attestation gate + disclaimer only; D-11 |
| Clinical hi/mr safety copy unreviewed | G-01 / G-02 | Needs named clinical signer |
| External LLM egress off by default | G-19 / G-28 | Needs signed DPA + security sign-off before `EXTERNAL_EGRESS` |
| Production MTTA not claimed | G-25 | Channels + 2‑min SLA ship; MTTA needs ops window — see [mtta-and-paging.md](../runbooks/mtta-and-paging.md) |
| SMS optional | G-06 residual | Email + Slack staff proven; SMS feature default off |
| ABDM not certified | G-09 | Stub `certified:false` |
| No RLS / column encryption / break-glass | G-10 | Predicate tests mitigate for pilot |
| WCAG 2.2 AA not signed | G-36 | Axe smoke + checklist only |
| Dual-API HA soak not yet on separate replicas | G-46 residual | Script + same-base evidence; run with `API_A≠API_B` for HA claim |

## Closed for pilot (in-repo + evidence)

- **G-06** email + Slack staff delivery — [notify-channels-probe-20261101T064929Z.json](./notify-channels-probe-20261101T064929Z.json)
- **G-18** vault/file secrets backend (`SECRETS_BACKEND=env|file|vault`) — unit tests + setup note; `.env` still valid locally
- **G-39–G-45, G-47–G-49** booking/stream/front-desk/Ollama residuals mitigated or closed per gaps v1.16 table

## Operator enablement

1. `NOTIFY_OPS_SUBJECT=<frontdesk Keycloak sub>`
2. `NOTIFY_SEND_EXTERNAL=true` with SMTP + Slack staff tokens
3. Staff Slack contacts use allowlisted **channel** IDs (bot DMs to arbitrary users fail with `channel_not_found`)
4. Optional: `SECRETS_BACKEND=vault` with `VAULT_ADDR` / `VAULT_TOKEN` / `VAULT_SECRET_PATH`
5. Re-prove channels: `scripts/probe_notify_channels.py --write-evidence`
