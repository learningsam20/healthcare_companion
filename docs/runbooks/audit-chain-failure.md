# Audit write failure or suspected audit tampering

| Field | Value |
|---|---|
| Alert | Audit insert/trigger failure; audit count stops; append-only trigger missing; suspected tampering or "chain mismatch" |
| Severity | S1 (compliance/safety). Stop clinical writes until audit integrity is understood |
| Owner | Compliance + security + E2 platform |
| Last reviewed | 2026-10-25 |

## Symptom

- Patient-linked reads or writes return HTTP 503 `database_unavailable`, and the API log shows `database.error`.
- The audit event count stops advancing while other activity continues, or an operator reports a gap.
- The append-only trigger is missing/disabled, or someone reports a hash-chain mismatch.
- The Compliance posture tile `audit_chain` shows `not_configured`.

## Impact

Audit is the evidence that patient-linked access and safety actions happened. This build has **no hash chain**: `audit_events` has an append-only trigger, but no `prev_hash`/`hash`, no verification job and no `audit_chain` value. The tile is intentionally `not_configured`. A "chain mismatch" cannot be verified here; do not claim it can. If the trigger is missing or rows were changed outside the application, treat it as suspected tampering. Stop clinical writes, preserve the database and logs, and escalate before attempting repair. Never backfill, edit or delete audit rows to make a check pass.

## First five minutes

1. Confirm scope and whether writes are still succeeding:
   ```bash
   ./scripts/status.sh
   curl -fsS http://localhost:5706/readyz | python3 -m json.tool
   ./scripts/logs.sh --service api --since 15m --no-follow
   ./scripts/logs.sh --service postgres --since 15m --no-follow
   ```
2. **Stop clinical writes.** This also stops background audit writers:
   ```bash
   docker compose stop api worker scheduler
   ```
   Tell the clinical owner that reads/writes are paused for an audit-integrity check. Do not leave the API up "for reads" if the audit insert path is failing.
3. Preserve the current state before any repair. Take an encrypted backup outside the repository:
   ```bash
   ./scripts/backup.sh --out /secure/audit-incident-<id> --encrypt <age-recipient> \
     --skip-objects --skip-keycloak --note "audit incident <id>"
   ```
   The backup contains PHI; restrict access and record its hash/location.
4. Capture read-only audit facts (no patient content):
   ```bash
   docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT tgname, tgenabled FROM pg_trigger
    WHERE tgrelid = 'audit_events'::regclass;
   SELECT count(*), min(created_at), max(created_at) FROM audit_events;
   SELECT action, actor_role, count(*)
     FROM audit_events
    WHERE created_at > now() - interval '24 hours'
    GROUP BY 1, 2 ORDER BY 3 DESC;
   SQL
   ```
5. Export the accessible audit window through the API if it is still readable; otherwise the backup is the evidence:
   ```bash
   ./scripts/export-audit.sh --from <YYYY-MM-DD> --to <YYYY-MM-DD> \
     --format json --out /secure/audit-export-<id>.json
   ```
6. Record who has database superuser/owner access and every command run. Do not restart repeatedly without a hypothesis.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| All writes 503, reads may work | DB unavailable, pool exhausted, disk full, missing table/trigger | restore DB service; keep writes stopped until audit inserts succeed |
| Audit insert fails only for some actions | schema/trigger/permission problem or a metadata value the trigger rejects | identify the action and error code; do not add a bypass |
| `audit_events` count frozen | writer stopped, trigger blocking, or app writing to another database | verify the API `DATABASE_URL` target; preserve both databases |
| Trigger absent or `tgenabled` not `O` | migration drift or deliberate tampering | preserve evidence; DBA/compliance must approve any trigger repair |
| Rows changed/deleted outside the app | suspected tampering or direct DB access | restrict DB access, preserve WAL/logs/backups, escalate to security |
| `audit_chain` tile `not_configured` | expected in this build | not an incident by itself; explain the limitation in writing |

There is no supported chain-verification command. Do not invent one and do not describe the tile as a passing chain check. If a stakeholder requires a hash chain, record that as an architecture gap, not as an operational result.

## Mitigation

- **Database availability:** restore Postgres service/disk first. The API fails closed with 503 when the audit insert cannot commit, which is the correct behaviour.
- **Trigger missing or disabled:** keep writes stopped. E2/DBA and compliance must approve a reviewed schema change that restores the trigger exactly as defined in `apps/api/migrations/versions/0001_initial.py`, or restore a verified backup. An ad-hoc trigger recreation without approval is not allowed.
- **Suspected tampering:** do not repair in place. Preserve the database, WAL/archive, host logs and access records; restrict credentials; follow [incident-response.md](./incident-response.md). If integrity cannot be established, compliance decides between restore and formal disclosure.
- **Application bug:** capture the failing action/event name and stack trace, fix forward in review, and replay only through normal application writes after the audit path is healthy. Never create "missing" audit events by hand.
- **Restore:** use [restore.md](./restore.md) only into an empty environment and only with compliance approval; restoring loses events after the backup and is itself a reportable gap.

## Rollback

There is no application rollback that repairs audit integrity. Roll back a deploy that introduced the failure, but keep writes stopped until a post-rollback insert and read are verified. Kubernetes:

```bash
kubectl -n sahyog rollout undo deployment/api
kubectl -n sahyog rollout undo deployment/worker
kubectl -n sahyog rollout status deployment/api
```

Do not roll back by restoring a database over the current one without the restore procedure and compliance approval.

## Evidence to capture

- Incident start/end, environment, release/image digests and the exact failing action/status code.
- Trigger state, table counts/timestamps, database role/access list and backup hash/location.
- Redacted logs and audit export; no clinical text, prompts, patient names or identifiers in tickets.
- Who approved stopping writes, any schema change or restore, and when.
- A written statement that hash chaining is not implemented in this build, with the gap reference.
- Client/compliance notification decision and recipient.

## Escalation

Compliance owns the integrity decision; security owns suspected tampering or unauthorized database access; E2 owns the database and application repair. The clinical owner is notified immediately because writes are stopped and patients need a human hand-off. If audit evidence may be incomplete for a period, do not resume clinical writes until compliance accepts the risk in writing.
