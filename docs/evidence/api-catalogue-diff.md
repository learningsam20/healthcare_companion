# API catalogue diff (design §7.5 vs as-built OpenAPI)

Generated: `2026-10-31T15:30:00.416873+00:00` by `scripts/diff_api_catalogue.py`

| Bucket | Count | Meaning |
| --- | ---: | --- |
| Matched | 57 | Same method + path in design and as-built |
| Renamed | 45 | Capability exists under a different path/verb |
| Proposed out of scope | 7 | Script-only / replaced / infra; **awaiting product sign-off** |
| Deferred (not built) | 5 | Functionality absent; product must implement or descope |
| Unresolved | 0 | Not yet classified |
| Invalid rename targets | 0 | Mapping points at a path that is not as-built |
| As-built only | 68 | Not in design tables |

Nothing here is marked out of scope by engineering. Status of the product decision:
[api-leftovers-product-note.md](./api-leftovers-product-note.md).

## Renamed (design to as-built)

| Design | as_built | note |
| --- | --- | --- |
| `GET /api/v1/me` | GET /api/v1/auth/me | identity under /auth |
| `GET /api/v1/me/notifications` | GET /api/v1/notifications | own by default |
| `POST /api/v1/me/notifications/{id}/read` | POST /api/v1/notifications/{notification_id}/read | owner-only |
| `GET /api/v1/me/notifications/{id}/deliveries` | GET /api/v1/notifications/{notification_id} | deliveries embedded in detail |
| `POST /api/v1/me/export` | GET /api/v1/me/export | GET, not POST |
| `GET /api/v1/slots` | GET /api/v1/doctors/{doctor_name}/slots | per doctor |
| `POST /api/v1/documents/uploads` | POST /api/v1/records/documents | single multipart upload; two-step presign not built |
| `POST /api/v1/documents/{id}/complete` | POST /api/v1/records/documents/{document_id}/ingest | ingest trigger replaces upload-complete |
| `GET /api/v1/documents` | GET /api/v1/records/documents | records prefix |
| `GET /api/v1/documents/{id}` | GET /api/v1/records/documents/{document_id} | records prefix |
| `GET /api/v1/documents/{id}/status` | GET /api/v1/records/documents/{document_id} | status is a field of document detail |
| `DELETE /api/v1/documents/{id}` | DELETE /api/v1/records/documents/{document_id} | records prefix |
| `GET /api/v1/documents/{id}/download-url` | GET /api/v1/records/documents/{document_id}/download | streamed download, not a presigned URL |
| `GET /api/v1/citations/{chunk_id}` | GET /api/v1/chat/citations/{chunk_id} | chat prefix |
| `POST /api/v1/encounters` | POST /api/v1/scribe/encounters | scribe prefix |
| `GET /api/v1/encounters/{id}` | GET /api/v1/scribe/encounters/{encounter_id} | scribe prefix |
| `POST /api/v1/encounters/{id}/audio/uploads` | POST /api/v1/scribe/encounters/{encounter_id}/audio | multipart audio upload |
| `POST /api/v1/encounters/{id}/audio/{audio_id}/complete` | POST /api/v1/scribe/encounters/{encounter_id}/audio/{transcript_id}/complete | transcript id |
| `POST /api/v1/encounters/{id}/scribe-runs` | POST /api/v1/scribe/encounters/{encounter_id}/runs | shorter name |
| `GET /api/v1/notes` | GET /api/v1/scribe/notes | scribe prefix |
| `GET /api/v1/notes/{id}` | GET /api/v1/scribe/notes/{note_id} | scribe prefix |
| `GET /api/v1/notes/{id}/versions` | GET /api/v1/scribe/notes/{note_id}/versions | scribe prefix |
| `GET /api/v1/notes/{id}/sources` | GET /api/v1/scribe/notes/{note_id}/sources | scribe prefix |
| `GET /api/v1/notes/{id}/download` | GET /api/v1/scribe/notes/{note_id}/download | scribe prefix |
| `POST /api/v1/notes/{id}/reservations` | POST /api/v1/scribe/notes/{note_id}/reservations | scribe prefix |
| `GET /api/v1/stock` | GET /api/v1/pharmacy/stock | pharmacy prefix |
| `GET /api/v1/stock/{medicine_id}` | GET /api/v1/pharmacy/stock/{item_id} | item id, not medicine id |
| `GET /api/v1/consents/{id}` | GET /api/v1/consents | list only; no get-by-id |
| `DELETE /api/v1/consents/{id}` | POST /api/v1/consents/{consent_id}/revoke | revoke action, not DELETE |
| `GET /api/v1/audit/events` | GET /api/v1/admin/audit | admin prefix |
| `GET /api/v1/audit/events/export` | GET /api/v1/admin/audit/export | admin prefix |
| `PATCH /api/v1/review-queue/{id}` | POST /api/v1/review-queue/{task_id}/claim | claim action |
| `POST /api/v1/review-queue/{id}/resolve` | POST /api/v1/review-queue/{task_id}/close | close action |
| `GET /api/v1/admin/feature-flags` | GET /api/v1/admin/flags | shorter name |
| `PATCH /api/v1/admin/feature-flags/{key}` | PATCH /api/v1/admin/flags/{key} | shorter name |
| `GET /api/v1/analytics/evals` | GET /api/v1/analytics/evaluations | full word |
| `GET /api/v1/analytics/eval-runs` | GET /api/v1/analytics/evaluations | run list is part of evaluations |
| `GET /api/v1/analytics/finops/usage` | GET /api/v1/analytics/finops | usage in summary |
| `PATCH /api/v1/analytics/finops/budgets/{id}` | PUT /api/v1/analytics/finops/budgets | bulk PUT |
| `PATCH /api/v1/analytics/finops/savings/{id}` | POST /api/v1/analytics/finops/savings | savings recorded via POST |
| `POST /api/v1/analytics/finops/export` | GET /api/v1/analytics/finops/export | GET |
| `GET /api/v1/analytics/metrics/{key}` | GET /api/v1/analytics/metrics | full catalogue, filter client-side |
| `POST /api/v1/analytics/insights/{id}/action` | POST /api/v1/analytics/insights/{insight_id}/decision | decision verb |
| `GET /api/v1/admin/config` | GET /api/v1/admin/governance | governance settings |
| `PATCH /api/v1/admin/config/{key}` | PATCH /api/v1/admin/governance | governance settings (body keys) |

## Proposed out of scope (unsigned)

| Design | reason |
| --- | --- |
| `GET /metrics` | Telemetry is OTLP push to the collector; no API pull endpoint. |
| `GET /api/v1/admin/users` | Keycloak user admin is an operator script (keycloak_admin.py). |
| `POST /api/v1/admin/users/invite` | Operator script: scripts/add-user.sh. |
| `PATCH /api/v1/admin/users/{id}/roles` | Operator script: scripts/add-user.sh --confirm. |
| `POST /api/v1/analytics/refresh` | Snapshot is an ARQ cron job; no manual HTTP trigger. |
| `GET /api/v1/admin/data-catalogue` | Catalogue lives in docs/data-contracts. |
| `GET /api/v1/admin/health` | Covered by /healthz, /readyz and scripts/status.sh. |

## Deferred - not built

| Design | reason |
| --- | --- |
| `PATCH /api/v1/me/preferences` | Preferences are the memory API (PUT /me/memory). |
| `PATCH /api/v1/me/memory/settings` | Opt-out is the opt_out key + POST /me/memory/purge. |
| `GET /api/v1/scribe/runs/{id}/sources` | Sources are on notes, not on runs. |
| `GET /api/v1/scribe/runs/{id}/events` | Scribe SSE progress stream not built. |
| `POST /api/v1/scribe/runs/{id}/resume` | Scribe run resume endpoint not built. |
