# Budget hard stop or cost anomaly

| Field | Value |
|---|---|
| Alert | LiteLLM budget hard stop; unexpected spend; cost per session/consultation spike; reconciliation variance |
| Severity | S1 if a clinical model path is hard-stopped; S2 for a cost anomaly with service still safe |
| Owner | Finance + E2 platform; E1 for routing changes |
| Last reviewed | 2026-10-25 |

## Symptom

- Model calls suddenly fail with HTTP 503 `gateway_unavailable`; LiteLLM logs mention budget/spend.
- FinOps showback jumps, or the monthly run rate exceeds the approved envelope.
- A load-test run trips its `budget_guard`.
- Someone reports that app usage and LiteLLM spend do not reconcile.

## Impact

`config/litellm.yaml` configures a LiteLLM gateway budget of **250 USD per 30 days**; when exhausted, LiteLLM refuses calls and the application surfaces 503, not a fabricated answer. `config/models.yaml` also declares advisory per-session (60,000 tokens / 0.25 USD) and monthly (250 USD, 80% warning) values, and `config/prices.yaml` declares monthly model/infra/notification envelopes; **none of these app-side values is enforced and no 80% alert rule exists in this deployment**. Observed cost comes from application `usage_records` (real-traffic only); the read-only reconciliation job compares them with LiteLLM spend logs and reports matched/unmatched counts, with `partial` when unmatched calls remain. Never edit, delete or backfill `usage_records` or LiteLLM spend logs to make a number match.

## First five minutes

1. Stop new cost: halt any load run, and do not raise budgets.
   ```bash
   docker compose stop loadgen
   ```
2. Capture the aggregate showback (no prompts, no patient rows):
   ```bash
   ./scripts/export-finops.sh --days 30 --format json --out /secure/finops-<date>.json
   ```
   Read `status`, `observed`, `by_purpose`, `monthly_run_rate_usd`, `price_version` and `reconciliation`.
3. Confirm gateway health and external egress state:
   ```bash
   curl -fsS http://localhost:5708/health/liveliness
   curl -fsS http://localhost:5706/api/v1/meta | python3 -m json.tool
   ```
4. Read LiteLLM and API logs for the budget error and affected purposes:
   ```bash
   ./scripts/logs.sh --service litellm --since 30m --no-follow
   ./scripts/logs.sh --service api --since 30m --no-follow
   ```
5. If the export endpoint is unavailable, use an aggregate-only read (never edit):
   ```bash
   docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT purpose, model_alias, traffic_class, count(*) AS calls,
          round(sum(cost_usd)::numeric, 4) AS cost_usd
     FROM usage_records
    WHERE created_at >= now() - interval '30 days'
    GROUP BY 1, 2, 3 ORDER BY 5 DESC;
   SQL
   ```
6. Record who ran any load test, its approval reference and its `--budget-usd`.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| LiteLLM refuses all calls with budget error | 30-day gateway budget exhausted | keep local-only routes; escalate to finance; do not raise the cap without approval |
| Spend concentrated in `rag_answer`/`judge` | external alias used more than expected | verify only de-identified purposes use external egress; review routing with E1 |
| Local aliases also failing | not a budget issue; gateway/local model down | follow [model-outage.md](./model-outage.md) |
| `reconciliation.status: partial` | unmatched calls remain (direct gateway traffic or recent calls inside the lag window) | keep showback labelled; review unmatched IDs; do not claim full reconciliation |
| `reconciliation.status: insufficient_data` | no reconciliation inside the freshness window | run the reconcile job; treat spend as unreconciled |
| App total differs from provider invoice | price catalogue/FX drift, missing usage row, or provider-side charge | preserve both sources; escalate to finance; never adjust rows to force a match |
| Spike aligns with a load test | synthetic traffic excluded from FinOps real-traffic totals | read the load-test summary and `synthetic_cost_usd`; no production budget exemption |

There is no supported reconciliation command or matched/unmatched variance report. Do not create one by writing a corrected row. The only trustworthy cost evidence in this build is the app-recorded aggregate export plus the provider invoice/spend exports, clearly labelled as unreconciled.

## Mitigation

- **Freeze spend:** stop load generation; keep `EXTERNAL_EGRESS_ENABLED=false`; cancel any planned eval run. RAG already falls back to `local_main` when external egress is disabled.
- **Restore clinical RAG after a hard stop:** with E1 and clinical approval, change `rag_answer.primary` to `local_main` in `config/models.yaml` and restart `api` and `worker`. This removes external spend and keeps the workflow available; `w3_draft`, STT, PII and embeddings must remain local.
- **Budget increase:** only finance can approve a new limit. Change `max_budget`/`budget_duration` in `config/litellm.yaml` (and the app envelopes for consistency), record the approval, and restart LiteLLM. Do not patch the running container.
- **Provider/key issue:** rotate the provider key per [key-rotation.md](./key-rotation.md); do not disable usage recording.
- **Suspected abuse or a leaked key:** treat as a security incident, stop external egress, preserve logs and follow [incident-response.md](./incident-response.md).
- **Do not:** edit `usage_records`, delete LiteLLM spend rows, `UPDATE` costs, re-run a load test with a larger budget, or claim reconciliation.

## Rollback

Revert an unapproved routing/budget change in review and restart the affected process:

```bash
./scripts/restart.sh --service litellm
./scripts/restart.sh --service api
```

Kubernetes:

```bash
kubectl -n sahyog rollout undo deployment/litellm
kubectl -n sahyog rollout undo deployment/api
kubectl -n sahyog rollout status deployment/litellm
```

A rollback that restores external spend also restores the budget risk; finance must accept it.

## Evidence to capture

- Budget configuration in force (`max_budget`, `budget_duration`, app envelopes), price version/FX and approval reference.
- Aggregate FinOps export and provider invoice/spend export, both labelled reconciled or unreconciled.
- Purpose/model/traffic-class totals and the load-test summary; no prompts or patient data.
- First budget error timestamp, affected workflows and human hand-offs.
- Every budget/routing change, approver and timestamps; confirmation that no usage or spend row was edited.

## Escalation

Finance owns the budget decision; E2 owns the gateway and spend plumbing; E1 owns routing. Clinical owner is notified when a hard stop blocks record answers or drafting. Security is notified for a suspected leaked key or unexplained external spend.
