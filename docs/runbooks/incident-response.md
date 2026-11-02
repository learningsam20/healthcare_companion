# Incident response and client notification

| Field | Value |
|---|---|
| Alert | Safety, privacy, security or availability event requiring coordinated response |
| Severity | S1/P0 page; S2/P1 urgent; S3/P2 operational. See the table below |
| Owner | engineering lead as incident commander; clinical, security and compliance owners by incident type |
| Last reviewed | 2026-10-25 |

## Symptom

Any of the following starts an incident: a suspected scope leak or missed red flag; identified data sent to an external model or channel; audit writes/integrity in doubt; a signed note with unverified content; a wrong-recipient notification; lost or corrupted patient-linked data; a leaked credential; a total clinical outage; or a load test affecting real users. Symptoms may arrive as an alert, a clinician report, a patient complaint or a security finding.

## Severity

| Level | Definition | Examples | Response |
|---|---|---|---|
| S1 (P0) | Immediate patient-safety, privacy, security or audit-integrity risk, or no safe clinical workflow | scope leak, missed red flag, PHI egress, audit write failure/tampering, signed corrupt note, key compromise, data loss | Declare immediately; page engineering lead + clinical/security; stop the line; incident bridge |
| S2 (P1) | Material degradation with a safe workaround, or a contained compliance/operational failure | model outage with human hand-off, queue backlog, analytics stale, one channel failing, planned rotation failure | Respond urgently; named owner; contain and monitor |
| S3 (P2) | Localized/operational issue with no patient-safety impact | single document extraction failure, cosmetic analytics gap, non-urgent backlog | Handle in normal operations; record if recurring |

When in doubt, start at S1 and downgrade only with the clinical/security owner's agreement. Severity is about patient and compliance impact, not how many alerts fired. The architecture uses P0/P1/P2; this table maps them to S1/S2/S3 for the runbooks.

## Stop-the-line triggers

Stop clinical writes or the affected pathway **first**, then investigate, for: any suspected scope leak or wrong-patient data; a missed or unacknowledged red flag; identified data crossing an external boundary; audit insert failure, missing trigger or suspected tampering; a signature over content that was not reviewed/grounded; a notification carrying clinical detail to the wrong recipient; a leaked signing, database or provider key; or corruption/loss of patient-linked data. Do not trade safety for availability. A clinician must always have a human hand-off path.

## First five minutes

1. **Declare and assign.** Name an incident commander (engineering lead), a scribe and the clinical/security/compliance leads needed. Record start time in UTC.
2. **Open an incident record outside the application.** This build has **no incident register API or `incident` table**; the review queue is for clinical review tasks, not incidents. Use the client's incident/ticketing system. Do not put patient data, prompts or secrets in it.
3. **Establish scope without exposing content.** Which environment, roles, workflows, patients (counts/IDs only where authorized), channels, models and time window? Is it ongoing?
4. **Contain using the narrowest control.** Prefer a channel/route stop over a full stack stop. Preserve logs, audit, snapshots and provider message IDs before changing state.
5. **Make the safe clinical call.** If the workflow cannot be trusted, tell the clinical owner to use the approved human process; do not let staff improvise around safety controls.
6. **Communicate on a schedule.** Give the clinical/security leads a short status at agreed intervals; record decisions and who approved them.

## Containment matrix

| Event | First containment | Runbook |
|---|---|---|
| API/dependency outage | restart the failing dependency; keep UI error honest; hand off | [api-unavailable.md](./api-unavailable.md) |
| Model/provider outage or blocked egress | keep local-only routes; do not widen egress; hand off | [model-outage.md](./model-outage.md) |
| PII gate failure or block storm | keep the gate closed; disable external route; preserve logs | [pii-gate-failure.md](./pii-gate-failure.md) |
| Audit write failure/tampering | stop API/worker/scheduler writes; encrypted backup; restrict DB access | [audit-chain-failure.md](./audit-chain-failure.md) |
| Queue backlog/stuck ingestion | stop new uploads if needed; restart one worker; never flush Redis | [queue-backlog.md](./queue-backlog.md) |
| Budget hard stop/anomaly | stop load/eval runs; keep external egress off; finance approval | [budget-cost-anomaly.md](./budget-cost-anomaly.md) |
| Analytics stale | label stale; capture a fresh snapshot; do not show zero | [analytics-stale.md](./analytics-stale.md) |
| Wrong-recipient notification | stop worker; correct contact/flag; assess recall limits | [notification-misdelivery.md](./notification-misdelivery.md) |
| Stale/corrupt scribe run or draft | do not sign; reject and start a new run where supported; preserve IDs | [checkpoint-corruption.md](./checkpoint-corruption.md) |
| OCR/STT unavailable or malformed document | fail visibly; use a real manual transcript; no fabricated content | [ingestion-ocr-failure.md](./ingestion-ocr-failure.md) |
| Key leak/rotation failure | rotate/disable the key; preserve provider logs; security lead | [key-rotation.md](./key-rotation.md) |
| Data loss/corruption | stop writers; preserve the damaged state; restore only with approval | [restore.md](./restore.md) |
| Load test hits real users | stop the generator; treat as an incident; check notifications/bookings | [load-abort.md](./load-abort.md) |
| Keycloak outage/admin lockout | restore auth; no bypass; clinical hand-off | [keycloak-outage.md](./keycloak-outage.md) |

For a suspected scope leak, do not "test" with another patient's record. Disable the affected retrieval/answer path, preserve the audit/trace IDs and involve the clinical/security owner. For PHI egress, also stop the external route and preserve the provider request metadata without the payload.

## Clinical and security escalation

- **Clinical owner:** decides whether care can continue, what hand-off staff use, whether patients need to be contacted, and whether a signed/unsigned note needs review. Never send clinical detail through an unapproved channel.
- **Security owner:** owns suspected unauthorized access, credential/key compromise, PHI egress and evidence preservation. Rotate only after preserving the logs needed to investigate, unless ongoing exposure requires immediate containment.
- **Compliance owner:** owns audit integrity, consent/scope, retention and disclosure decisions. They decide whether a restore or a formal report is required.
- **E2/E1/E4:** platform, agent/model and integration owners execute the technical containment under the incident commander.

## Client notification

The engineering lead and client operations/compliance owner decide whether, when and how to notify. Notification must be factual: what is known, what is not known, the affected window and workflows, the containment taken, the patient action (if any) and the next update. Do not speculate, do not include patient identifiers or clinical content, and do not use a patient-facing Slack/SMS channel for incident detail. Use the client's approved contact list and channel. Record who approved the wording and when it was sent. There is no bulk recall endpoint; once an external provider accepts a message, recall cannot be guaranteed.

## Evidence to capture

- Incident ID, severity, start/end in UTC, environment, release/image digests, incident commander and approvers.
- Alert/report source, affected workflows/roles, counts and request/trace/run IDs; no patient names, prompts, note text, contacts or secrets.
- Timeline of commands and decisions, including any stop-the-line action and who authorized it.
- Audit export, snapshot, logs, backup hash/location and provider message IDs; chain-of-custody for copies.
- Clinical hand-off, patient-safety assessment, notification wording/recipient/time and any regulatory decision.
- What worked, what failed, missing runbook/alert and the corrective actions with owners/dates.

## Post-incident review

Hold a blameless review promptly after containment, with clinical, security, compliance and engineering. Establish the contributing causes, whether a control failed or was missing, the patient/compliance impact and the detection gap. Produce actions with owners and due dates; update the affected runbook and [gaps.md](../gaps.md) if a control is absent; add a clinical/eval case where relevant; schedule a drill. Do not close the incident until containment is verified, evidence is preserved, required notifications are sent and actions are assigned. Do not mark a runbook "drilled" without a record.

## Drill

An S1 tabletop is required before a production gate: suspected PHI egress plus a wrong-recipient notification, with clinical/security/compliance participation. A second tabletop should cover audit write failure and stop-the-line. **No incident-response drill record exists yet.** Record scenario, participants, timings, decisions, evidence path and corrective actions.

## Escalation

engineering lead on-call is the incident commander. Escalate to the client's clinical/operations owner for patient impact, the security owner for compromise/egress, and compliance for audit/consent/disclosure. If the incident involves a real patient, the clinical owner's process takes precedence over engineering convenience.
