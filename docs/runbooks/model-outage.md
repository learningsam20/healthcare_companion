# Model gateway or provider outage

| Field | Value |
|---|---|
| Alert | LiteLLM 5xx/timeout; `gateway_unavailable` responses; model circuit open; local provider down |
| Severity | S1 if clinical drafting or cited record answers are blocked; S2 if only an external evaluation route is affected |
| Owner | E1 agent behaviour + E2 platform |
| Last reviewed | 2026-10-25 |

## Symptom

- Chat returns HTTP 503 `gateway_unavailable`; the user message is saved but no reply is produced.
- Record questions return `status: model_unavailable` with sources and no answer.
- A scribe run ends `failed` with `model_unavailable` and a doctor review task is opened.
- LiteLLM is unhealthy, restarting, or logging upstream timeout/connection errors.
- External calls may be blocked by policy instead of failing: chat records `chat.reply_blocked` with reason `external_egress_blocked`.

## Impact

Every generative and embedding call goes through LiteLLM. `w3_draft`, conversation, summarisation, STT and embeddings are local-only. `rag_answer` and `judge` may use an external alias only for de-identified text. An outage must degrade to a visible failure or a local route, never to a fabricated answer, an unsigned "completed" note, or identified text sent externally. Ingestion also depends on local embeddings, so uploads can fail while chat still works.

## First five minutes

1. Confirm scope:
   ```bash
   ./scripts/status.sh
   curl -fsS http://localhost:5708/health/liveliness
   curl -fsS http://localhost:5706/readyz | python3 -m json.tool
   ```
2. Record the effective routes and egress state (no secrets):
   ```bash
   curl -fsS http://localhost:5706/api/v1/meta | python3 -m json.tool
   ```
3. Read the gateway and application logs:
   ```bash
   ./scripts/logs.sh --service litellm --since 15m --no-follow
   ./scripts/logs.sh --service api --since 15m --no-follow
   ./scripts/logs.sh --service worker --since 15m --no-follow
   ```
4. Check host pressure; a local model needs memory:
   ```bash
   docker stats --no-stream
   df -h
   ```
5. If a deploy, model pull or config change preceded the failure, freeze further changes and record the image/config digest.

## Diagnosis

| Check | Command | Interpretation |
|---|---|---|
| Gateway process | `curl -fsS http://localhost:5708/health/liveliness` | Failure: LiteLLM down, database unreachable, OOM or bad config |
| Local model host | `curl -fsS http://localhost:11434/api/tags` for host Ollama, or `curl -fsS http://localhost:5728/api/tags` in the `full` profile | Failure: local provider unreachable or no model loaded |
| Model list | `docker compose exec ollama ollama list` (`full` only) | Missing/renamed model; do not substitute an unpinned model |
| Router fallback | `grep -n "fallbacks:\\|allowed_fails\\|cooldown_time" config/litellm.yaml` | Confirms `local_main -> local_small` and `external_reasoning -> local_main`; circuit state itself has no operator endpoint |
| Gateway errors | `./scripts/logs.sh --service litellm --since 15m --no-follow` | Distinguish upstream timeout, budget exhaustion, bad key or invalid model |
| Audit counts | `./scripts/export-audit.sh --action chat.reply_failed --from <YYYY-MM-DD> --to <YYYY-MM-DD> --format json --out <secure-path>` | Confirms application-visible failures; no prompts or replies are in audit |
| Egress block | same export with `--action chat.reply_blocked`; inspect `/api/v1/meta` `adapters.external_llm` | If `disabled`, external purposes must use a local fallback; do not widen egress to restore service |

The LiteLLM router opens a circuit after `allowed_fails: 1` and cools down for 30 seconds. This build has no circuit-state API or alert; infer it from logs and from calls recovering after the cooldown. `records.answer_model_unavailable` does not record whether the cause was outage or egress policy, so correlate with `/meta`, PII logs and the PII runbook.

## Mitigation

- **Gateway down:** restart it, then re-check health and one synthetic chat:
  ```bash
  ./scripts/restart.sh --service litellm
  ```
- **Local provider down:** start/pull the pinned model. In the `full` profile:
  ```bash
  docker compose exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
  docker compose exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
  ```
  For host-installed Ollama, use the same pinned tags with the host `ollama` CLI.
- **External provider down:** keep the API up. `rag_answer` already declares `local_main` as fallback; if the application is not falling back, switch that purpose's primary to `local_main` in `config/models.yaml` with E1 and clinical approval, then restart `api` and `worker`. Identified text must never be routed externally to compensate.
- **Blocked egress:** do not disable the PII gate or set `EXTERNAL_EGRESS_ENABLED=true` to clear the error. Follow [pii-gate-failure.md](./pii-gate-failure.md).
- **Scribe run failed:** the run is already `failed` and a review task exists. Do not sign anything; after the gateway is healthy the doctor can start a new run on the same ready transcript. If the failure was input-related, use the manual transcript path in [ingestion-ocr-failure.md](./ingestion-ocr-failure.md).
- **Record answer unavailable:** the user may see the resolved sources but must not receive an invented summary; retry after recovery or hand off to a clinician.

## Rollback

Revert the route or config change in review, then restart the affected processes:

```bash
./scripts/restart.sh --service api
./scripts/restart.sh --service worker
```

Kubernetes:

```bash
kubectl -n sahyog rollout undo deployment/api
kubectl -n sahyog rollout undo deployment/litellm
kubectl -n sahyog rollout status deployment/api
```

A rollback must not restore an external route for identified text or re-enable an unapproved provider.

## Evidence to capture

- Alert/start/end timestamps, environment, image and config digests, model aliases and pinned model tags.
- LiteLLM/API/worker log excerpts with event names only; no prompts, replies, patient identifiers or keys.
- `/readyz` and `/meta` payloads before/after mitigation (no secrets).
- Counts of `chat.reply_failed`, `chat.reply_blocked`, `records.answer_model_unavailable` and `scribe.run_failed`.
- Who approved any alias/fallback change and why.
- Whether any external call was attempted while the local route was unavailable.

## Escalation

E2 owns the gateway and host; E1 owns routing and agent behaviour; the clinical owner decides whether an unavailable workflow needs a human hand-off or patient communication. Security is notified for suspected key compromise or an unapproved external route. Never trade privacy or signature controls for availability.
