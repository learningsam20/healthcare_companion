# PII gate failure or block storm

| Field | Value |
|---|---|
| Alert | `mcp-pii` health failing; external model calls refused; PII block rate spikes |
| Severity | S1 (privacy/safety) |
| Owner | Security + E1; clinical owner for workflow impact |
| Last reviewed | 2026-10-25 |

## Symptom

- `/readyz` marks `mcp_pii` down in the `core`/`full` profile.
- Chat or scribe calls fail with a PII/egress error instead of an answer.
- The PII block counter rises sharply, or legitimate text is repeatedly blocked (block storm).
- The API logs `PII_FAIL_CLOSED` or an egress-gate rejection (event names only; no content).

## Impact

By design, the external egress gate fails closed: no identified health text may reach an external model. Patients may receive a refusal or human hand-off. The local W3 path is unaffected if it does not require external egress. A block storm can look like an outage, but disabling the detector is a privacy incident, not a fix.

## First five minutes

1. Confirm the gate state:
   ```bash
   curl -fsS http://localhost:5715/healthz
   curl -fsS http://localhost:5706/readyz | python3 -m json.tool
   ```
2. Check the PII service and API logs, redacted:
   ```bash
   ./scripts/logs.sh --service mcp-pii --since 15m --no-follow
   ./scripts/logs.sh --service api --since 15m --no-follow
   ```
3. Determine whether the failure is **availability** (detector down/model missing) or **policy** (text blocked because a detector fired). Do not print the text. Use request IDs, detector labels/confidence buckets and counts.
4. If a deploy or model change preceded the alert, freeze changes and record the image/config digest.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| `mcp-pii` unreachable/timeout | container down, model load failure, memory pressure | restart `mcp-pii`; check `docker stats`; do not bypass |
| Composite detector returns errors | model files missing/corrupt, tokenizer mismatch | restore the pinned model artifacts; verify health |
| Block rate spikes with no code change | new document type, locale/mixed script, provider model change | sample **detector labels only**, review threshold with security; no raw content in tickets |
| Only external calls fail, local works | egress policy/proxy or provider issue | keep local fallback; check `egress-proxy`/allowlist; do not widen allowlist without approval |
| Gate is healthy but API still refuses | client-side validation, token/PII token mismatch, or a stale config | check settings and readiness; restart API after correcting config |

## Mitigation

- **Restore the detector:** restart the service and confirm health; if the model cannot load, keep the gate closed and route affected workflows to a human hand-off.
- **Contain a suspected leak:** disable the external route/profile (`LITELLM` external aliases or egress proxy), preserve logs, and notify the security owner immediately. Do not delete evidence.
- **Block storm:** reduce false positives only through an approved threshold/allowlist change with security sign-off and a regression run; never set `PII_FAIL_CLOSED=false` to clear an alert.
- **Provider-side change:** switch to the local alias for W3/identified text; external aliases remain de-identified-only.

## Rollback

Revert the PII config/model change in git and restart `mcp-pii` and `api`:

```bash
./scripts/restart.sh --service mcp-pii
./scripts/restart.sh --service api
```

If the K8s deployment is affected:

```bash
kubectl -n sahyog rollout undo deployment/mcp-pii
kubectl -n sahyog rollout status deployment/mcp-pii
```

A rollback must not re-enable external egress if the gate is unhealthy.

## Evidence to capture

- Alert timestamps, environment, release digests, PII engine/model versions.
- Detector labels, confidence buckets, block/allow counts and request IDs — **no text, names, contacts or patient IDs**.
- Whether any external call was attempted while the gate was down; provider/egress logs with identifiers redacted.
- Threshold/allowlist decisions and approver names.
- Notification to the security/compliance owner and any client notification decision.

## Escalation

Security owner immediately for any suspected egress or misconfiguration; E1 for model/routing; clinical owner for workflow impact and hand-off. If PHI may have left the boundary, treat it as a privacy incident, preserve evidence and follow the client's incident process. Never "test" the gate with real patient data.
