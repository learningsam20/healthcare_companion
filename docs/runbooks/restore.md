# Restore from backup

| Field | Value |
|---|---|
| Alert | Suspected data loss/corruption; failed migration; restore drill |
| Severity | S1 if patient-linked data is lost or integrity is in doubt |
| Owner | E2 + compliance |
| Last reviewed | 2026-10-25 |

## Symptom

A table or object is missing after a failed migration, the database refuses writes, audit continuity is broken, or a scheduled restore drill is due. A restore is also required when rebuilding an empty environment from evidence.

## Impact

Restoring replaces application data, object bytes and possibly the Keycloak realm. Done against a non-empty environment it can destroy newer work. Done without stopping writers it can produce an inconsistent state. The backup contains PHI and Keycloak client secrets; treat it as sensitive material.

## Preconditions

- The target environment is empty, or the incident owner has explicitly approved replacing it.
- You have the backup directory/archive and, if encrypted, the `age` identity.
- You know the last known-good release and the backup manifest's Alembic revision.
- The stack can be stopped without affecting an active clinical workflow. If patients are mid-workflow, arrange a human hand-off first.
- Store the backup outside the repository with mode `0700`; never copy it into chat or a ticket.

## First five minutes

1. Freeze writes. Stop the application services (the restore script stops the ones it needs, but an operator should confirm no other writer is active):
   ```bash
   ./scripts/stop.sh
   ```
2. Preserve the current state before replacing anything: take a new backup of the damaged environment if it is readable.
3. Identify the restore point and its manifest:
   ```bash
   ls -l <backup-dir>
   cat <backup-dir>/manifest.json   # counts, hashes, revision, release; no content
   ```
4. Verify the target is the intended environment (hostname, namespace, `.env` profile). A restore into the wrong environment is a destructive action.

## Restore

```bash
./scripts/restore.sh --from <backup-dir-or-archive> --confirm
# encrypted archive:
./scripts/restore.sh --from <backup.tar.gz.age> --identity <age-identity> --confirm
```

The script refuses to overwrite existing application data or objects. Use `--skip-objects`, `--skip-keycloak` or `--skip-smoke` only when the incident owner agrees; a skipped component is recorded as an incomplete restore. `--allow-existing-realm` overwrites realm users and needs explicit approval.

The script:

- restores Postgres and the telemetry databases when present;
- restores the six object buckets;
- imports the Keycloak realm;
- reruns migrations to head;
- verifies counts/hashes and validates configuration;
- runs the smoke suite unless skipped.

## Verification

1. `curl -fsS http://localhost:5706/readyz | python3 -m json.tool` — all required dependencies up.
2. `./scripts/smoke.sh --skip-ui` — auth, chat, grids, sources and notification declarations.
3. Check row/object counts against the manifest; check the Alembic revision is head.
4. Sign in as one user of each role through real Keycloak; confirm consent/scope behaviour on a synthetic patient.
5. Confirm audit continuity and that the restored flags/routes match the recorded release.
6. Record the measured restore duration and compare with the RTO target (4 h). This is evidence for G-11, not a production HA claim.

## Rollback

A restore is not transactional across database, objects and Keycloak. If post-restore verification fails, stop and **do not** keep layering fixes. Preserve the failed target, return to the pre-restore backup (if one was taken), and escalate. Never edit audit or clinical rows to make verification pass.

## Evidence to capture

- Backup manifest hash/revision, restore start/end, operator and approver.
- Output of readiness, smoke and count verification (identifiers redacted).
- Any skipped component and why; measured RPO/RTO.
- Credential rotation decision if the backup was exposed; the archive's location and retention.

## Escalation

E2 owns the restore. Compliance is notified for any patient-linked data loss or audit break. Security is notified if the backup was mishandled. The clinical owner decides whether affected workflows need a human hand-off or patient communication.
