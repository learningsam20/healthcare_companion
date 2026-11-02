# Queue backlog, stuck ingestion or notification outbox

| Field | Value |
|---|---|
| Alert | ARQ queue depth rising; document stuck in `queued`/`processing`; notification deliveries queued past threshold; worker unhealthy |
| Severity | S2 (S1 if patient-facing notifications are misdelivered or a clinical document is needed for care) |
| Owner | E2 platform + E4 integrations |
| Last reviewed | 2026-10-25 |

## Symptom

- The worker restarts, is unhealthy, or its logs show repeated job failures.
- A document stays `queued` or `processing` and never becomes `indexed`/`failed`.
- Notification deliveries remain `queued` with `attempts` not advancing, or the oldest queued delivery is more than 10 minutes old.
- Redis memory is high, `sahyog:worker` is growing, or API logs show `records.queue.unavailable`.

## Impact

Ingestion delays mean a document cannot be retrieved or cited. Notification delays mean a patient/staff message is late; a misconfigured channel can also send the wrong message. Clinical note signing does not depend on the queue, but a doctor may be waiting for a transcript or document. Do not "fix" a backlog by flushing Redis, deleting job keys, or bulk-updating rows: that loses auditability and can duplicate or misroute messages.

## First five minutes

1. Confirm the worker, Redis and API state:
   ```bash
   ./scripts/status.sh
   docker compose ps worker redis
   docker compose exec worker arq app.worker.WorkerSettings --check
   ```
2. Measure the ARQ queues. Ingestion/notification work is on `sahyog:worker`
   (`ARQ_WORKER_QUEUE`); retention/analytics cron work is on `sahyog:scheduler`
   (`ARQ_SCHEDULER_QUEUE`). They are intentionally separate so a worker cannot
   claim a job function it does not register:
   ```bash
   docker compose exec redis redis-cli zcard sahyog:worker
   docker compose exec redis redis-cli zrange sahyog:worker 0 9 withscores
   docker compose exec redis redis-cli zcard sahyog:scheduler
   docker compose exec redis redis-cli --scan --pattern 'arq:in-progress:*'
   ```
   Scores are enqueue times in milliseconds. Convert the oldest with `date -r $((<score>/1000))`.
3. Count work by state (no patient rows):
   ```bash
   docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT status, error_code, count(*)
     FROM documents GROUP BY 1, 2 ORDER BY 3 DESC;
   SELECT channel, status, last_error_code, count(*), min(scheduled_at), max(scheduled_at)
     FROM notification_deliveries GROUP BY 1, 2, 3 ORDER BY 4 DESC;
   SQL
   ```
4. Read worker and API logs for the failure code, not message bodies:
   ```bash
   ./scripts/logs.sh --service worker --since 30m --no-follow
   ./scripts/logs.sh --service api --since 30m --no-follow
   ./scripts/logs.sh --service redis --since 30m --no-follow
   ```
5. If a deploy or config change preceded the backlog, freeze further changes and record the image/config digest.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| Worker unhealthy/restarting | bad env, DB/Redis auth, OOM, image crash | fix the dependency; restart one worker; do not scale out to drain |
| `sahyog:worker` deep, worker healthy | throughput or a slow job (embeddings, large PDF) | check host/model latency; let it drain; reduce new uploads |
| Queue deep, no `arq:job:*` keys | Redis lost data or was flushed | jobs are gone; re-drive documents via the API, never by editing Redis |
| Document `processing` with no in-progress/job key | orphaned run (API/worker died mid-job); no reconciler in this build | do not SQL-reset it; re-upload the original file as a new document and preserve the old one as evidence |
| Document `failed` with `ocr_not_configured`, `pdf_unreadable`, `no_extractable_text` | deterministic extraction failure, not transient | follow [ingestion-ocr-failure.md](./ingestion-ocr-failure.md); retrying will not help |
| Notification `queued`, `attempts=0` | worker cron not running or delivery future-scheduled by quiet hours | check worker; expect quiet-hours delay until 08:00 IST |
| Notification `failed`, `attempts=3` | adapter/credential/recipient failure | fix channel/contact; do not reset attempts or edit rows |
| `records.queue.unavailable` | enqueue failed and ingestion ran in-process | do not restart the API until the document settles; an API restart loses that in-process task |

The worker dispatches notifications every minute and processes at most 10 jobs per burst with a 300-second job timeout. Notification retries are 3 with 30/120/600-second backoff. There is no dead-letter CLI, no manual requeue command and no delivery claim/lock; adding worker replicas to drain a backlog can duplicate dispatches.

## Mitigation

- **Restart the worker** after fixing the cause:
  ```bash
  ./scripts/restart.sh --service worker
  ```
  Environment changes need `./scripts/start.sh --profile <profile>`; `restart.sh` keeps the old environment.
- **Stop delivery, not the database:** if messages may be going to the wrong recipients, stop the worker first:
  ```bash
  ./scripts/stop.sh --service worker
  ```
  Queued deliveries remain in Postgres. Fix contacts/config, then restart the worker. See [notification-misdelivery.md](./notification-misdelivery.md).
- **Retry a transient document failure** through the supported endpoint (not for quarantined or `processing` documents):
  ```bash
  curl -fsS -X POST http://localhost:5706/api/v1/records/documents/<document-id>/ingest \
    -H "Authorization: Bearer <operator-token>"
  ```
  Prefer the UI action, which already holds a real session. A document that is `processing` cannot be retried by this endpoint.
- **Orphaned `processing` document:** re-upload the same source file as a new document with a new title; the old row remains as evidence. Do not update `documents.status` directly.
- **Notification backlog:** let the worker retry. If a delivery is permanently failed, correct the contact and use the approved notification UI to send again only after checking the template and recipient; there is no idempotency key, so a duplicate is possible.
- **Redis pressure:** check `docker compose exec redis redis-cli info memory`; free host memory or restart Redis only with E2 approval. Never run `FLUSHDB`, `DEL sahyog:worker` or `KEYS *` in production.

## Rollback

Roll back a bad worker image, then verify the queue drains and document/notification states advance:

```bash
kubectl -n sahyog rollout undo deployment/worker
kubectl -n sahyog rollout status deployment/worker
```

Compose has no automatic previous image; redeploy the last recorded worker image. A Redis rollback is not a data restore: if Redis lost queued jobs, re-drive documents through the API and treat lost notifications as an incident.

## Evidence to capture

- Queue depth/oldest score over time, worker health and restart count, image/config digests.
- Counts by document status/error code and by delivery channel/status/error code; no message bodies, addresses or patient identifiers.
- Job IDs and trace IDs only; no payloads or extracted text.
- Actions taken (restart/stop/re-upload), who approved them, and duplicate-delivery assessment.
- Whether any in-process ingestion was lost on an API restart.

## Escalation

E2 owns Redis, the worker and database state; E4 owns provider adapters; the clinical owner is notified when a document is needed for care or a patient-facing message is late. Security/compliance is notified if a notification may have reached the wrong recipient or if queue data was lost.
