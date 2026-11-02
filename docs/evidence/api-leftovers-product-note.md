# G-38 — design-table leftovers: product decision note

**Status: NOT SIGNED. G-38 stays `Mitigated`.** This note is an engineering classification
prepared for the product owner. It is not a product decision and must not be cited as one.

Source of truth for the lists below: [api-catalogue-diff.md](./api-catalogue-diff.md)
(regenerate with `scripts/regen_architecture_catalogue.py` then
`scripts/diff_api_catalogue.py --strict`; the second step exits non-zero if a design row is
unclassified or a rename target is not as-built).

## What engineering did

| Class | Count (at last regen) | Engineering action |
| --- | ---: | --- |
| Matched | 57 | none needed |
| Renamed (capability exists, different path/verb) | 45 | Mapped and verified against the as-built catalogue. Design tables in architecture §7.5 stay a target map. |
| Proposed out of scope | 7 | Listed with reasons; **needs your sign-off** |
| Deferred / not built | 5 | Listed with reasons; **you must implement or descope** |

One alias was added in code because it closes a real patient-facing gap: design
`POST /api/v1/me/contacts/{id}/verify` now exists (plus `.../request-verification`), owner-only.
Other renames were *not* aliased: duplicating routes only to match design names would add
surface area without adding capability.

## Decisions requested

Mark each row **Accept out of scope** or **Implement**.

| Design path | Proposed class | Reason | Decision |
| --- | --- | --- | --- |
| `GET /metrics` | out of scope | OTLP push to collector; no API pull endpoint | |
| `GET /api/v1/admin/users` | out of scope | Keycloak admin is an operator script | |
| `POST /api/v1/admin/users/invite` | out of scope | `scripts/add-user.sh` | |
| `PATCH /api/v1/admin/users/{id}/roles` | out of scope | `scripts/add-user.sh --confirm` | |
| `GET /api/v1/admin/health` | out of scope | `/healthz`, `/readyz`, `scripts/status.sh` | |
| `GET /api/v1/admin/data-catalogue` | out of scope | catalogue is `docs/data-contracts` | |
| `POST /api/v1/analytics/refresh` | out of scope | snapshot is an ARQ cron job | |
| `PATCH /api/v1/me/preferences` | deferred | preferences = memory API | |
| `PATCH /api/v1/me/memory/settings` | deferred | opt-out = `opt_out` key + purge | |
| `GET /api/v1/scribe/runs/{id}/sources` | deferred | sources are on notes | |
| `GET /api/v1/scribe/runs/{id}/events` | deferred | scribe SSE stream not built | |
| `POST /api/v1/scribe/runs/{id}/resume` | deferred | resume endpoint not built | |

## Sign-off

| Field | Value |
| --- | --- |
| Product owner | _unsigned_ |
| Date | _unsigned_ |
| Decision reference | _none_ |

Until the table above has a decision on every row, signed by the product owner, G-38 cannot move to `Closed`.
