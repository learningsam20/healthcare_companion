# Runbook: PII egress gate

## Control

No external model or cloud STT call may leave the boundary unless the local
**composite** PII engine (`engine=composite`, `not_clinical_grade=false`) redacts
the payload and residual detect count is zero.

Enforcement points:

1. `LlmGateway._route` — every external alias
2. API lifespan — `EXTERNAL_EGRESS_ENABLED=true` refuses startup without `composite_ready`
3. Cloud STT — requires egress + PII URL + `ALLOW_CLOUD_STT`

Regex fallback (`engine=regex_fallback`) is **never** sufficient for egress.

## Prerequisites

```bash
./scripts/download_models.sh
# mounts data/models into mcp-pii (GLiNER + Presidio)
curl -sS -H "X-Sahyog-Context: …" http://localhost:5715/tools/detect \
  -d '{"text":"test@example.com"}' | jq .result.engine
# expect: "composite"
```

## Incident: egress blocked

1. Confirm `EXTERNAL_EGRESS_ENABLED` was intentional.
2. Check mcp-pii health and `engine` on `/tools/detect`.
3. If `regex_fallback`, restore model weights and restart mcp-pii.
4. Do not disable the gate or treat regex as composite.

## Related

- G-19 / G-28 in `docs/gaps.md`
- Alert annotation `runbook_url` in `docker/prometheus/alerts.yml`
