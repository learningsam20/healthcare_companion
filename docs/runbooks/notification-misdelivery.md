# Notification misdelivery or wrong-recipient send

| Field | Value |
|---|---|
| Alert | Recipient reports a message for someone else or the wrong channel; Slack workspace/channel mismatch; unverified or opted-out contact received external copy |
| Severity | S1 if PHI/clinical detail reached the wrong person or a patient received another patient's message; S2 for a neutral wrong-channel or staff-only copy |
| Owner | E4 integrations + security/compliance; clinical owner for patient-facing impact |
| Last reviewed | 2026-10-25 |

## Symptom

- A patient, caregiver or staff member reports an email, SMS or Slack message that was not meant for them.
- The Notifications inbox shows a `sent` delivery whose recipient, contact address or Slack channel is wrong.
- A message appears in the wrong Slack workspace/channel, or `SLACK_*_WORKSPACE_ID` does not match the contact's `workspace_id`.
- A contact was expected to suppress (`recipient_unverified`, `opt_in_required`, `workspace_mismatch`) but an external delivery exists.

## Impact

In-app notifications are the source of truth; email, SMS and Slack are best-effort copies. External channels are off by default: `config/notifications.yaml` enables email, but `NOTIFY_SEND_EXTERNAL` defaults to `false`, and SMS/Slack are disabled. Do not enable a channel to "test" a fix.

A misdelivery may disclose appointment information even when the template is marked `clinical_detail: false`. Treat any clinical detail, attachment, patient name or wrong-patient send as a privacy incident. The API has **no recall, cancel or delete endpoint**; stopping the worker is the only immediate way to stop dispatch.

## First five minutes

1. Stop external dispatch before changing any contact or flag:
   ```bash
   ./scripts/stop.sh --service worker
   ```
   The API can still create in-app notifications and queue external deliveries while the worker is stopped. Do not restart it until the queue and contacts are reviewed.
2. Record the notification in the UI: **Notifications → Inbox**, enable **All users** (admin), open the row, and capture the notification ID, template/version, recipient role, channel, delivery status, attempts and provider message ID. Do not copy message bodies, addresses or patient identifiers into tickets.
3. Review the contact in **Notifications → Contacts** (admin): channel, `verified`, `opt_in`, `workspace_id`. A contact is marked verified by operator attestation; this build has no verification workflow.
4. Disable the affected runtime channel in **Governance → Flags** (`notifications_email`, `notifications_sms`, `notifications_slack_staff`, `notifications_slack_patient`). The change is audited as `admin.feature_flag_changed`. Other API replicas load the override on restart, so a Kubernetes rollout is needed for the change to reach every replica.
5. Page security/compliance immediately if the message contained clinical detail, an attachment, or reached a different patient. Notify the clinical owner before any corrective patient contact.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| Email/SMS `sent` to the wrong address | contact address was wrong, shared or changed after the send; `verified=true` did not prove ownership | keep worker stopped; trace `notifications.contact_upserted`; correct the contact only after queued deliveries are resolved |
| Patient Slack copy in a staff channel or another workspace | contact `address` is a channel/user ID from the wrong workspace; workspace check only covers `workspace_id`, not the channel | remove the bot from the wrong workspace, rotate the Slack token if exposed, disable Slack flags |
| Expected suppression did not happen | `NOTIFY_SEND_EXTERNAL=true`, channel enabled in config and flag enabled, template not clinical, contact verified | compare config, flags and contact; do not edit delivery rows to "recreate" suppression |
| Clinical detail in an external message | template is wrongly marked non-clinical, or caller injected unsafe template data | S1 privacy incident; preserve the notification and escalate before any resend |
| Duplicate or multiple recipients | shared contact row, wrong `recipient_subject`, or a manual resend after a retry | stop resends; record duplicates; no idempotency key exists |
| Slack `slack_rejected`/wrong channel | bot lacks access, channel ID is stale, or `SLACK_ALLOWED_CHANNELS` is wrong | fix in Slack admin; do not widen the allowlist without approval |

## Mitigation

- **Contain first:** leave the worker stopped until every affected delivery is accounted for. Do not delete the notification, delivery, contact or audit rows.
- **Queued deliveries read the contact at dispatch time.** Changing an address while a delivery is queued can send the old message to the new address. The supported safe sequence is: keep the worker stopped, set the affected contact `verified=false` (or leave it unverified), start the worker briefly so queued rows become `suppressed`, confirm no `sent` rows were added, then stop the worker again and correct/re-verify the contact with the right address.
- **Disable the channel** in Governance for the remainder of the incident. For a full external stop, set `NOTIFY_SEND_EXTERNAL=false` in the environment and recreate API and worker with `./scripts/start.sh --profile <profile>`; `restart.sh` keeps the old environment.
- **Slack containment:** remove the app/bot from the wrong workspace or channel, rotate `SLACK_BOT_TOKEN` with the provider, and verify `SLACK_STAFF_WORKSPACE_ID`/`SLACK_PATIENT_WORKSPACE_ID`. The app cannot delete a message.
- **Provider-side recall:** open a provider ticket using `provider_message_id`. Email recall is not guaranteed, SMS recall is generally impossible, and Slack deletion requires a workspace admin. Record what the provider confirms.
- **Corrective contact:** use approved neutral wording, approved by the clinical/security owner. Do not use the same broken channel until it is fixed, and do not include clinical detail.

### Recall limits

There is no `POST /recall`, no delivery cancellation and no outbox edit. `POST /api/v1/notifications/{id}/read` only marks an in-app notification read; it does not unsend anything. Once a delivery is `sent` with a provider message ID, the app can only ask the provider and record the outcome.

## Rollback

Re-enable a channel only after the root cause is fixed, the queue is clean and a synthetic test recipient succeeds:

```bash
./scripts/restart.sh --service worker
```

Environment or config changes need a controlled recreate:

```bash
./scripts/start.sh --profile <profile>
```

For Kubernetes, roll back the bad config/image and restart both API and worker; runtime flag overrides persist in the database:

```bash
kubectl -n sahyog rollout restart deployment/api deployment/worker
kubectl -n sahyog rollout status deployment/api deployment/worker
```

Never roll back by editing or deleting notification/delivery rows.

## Evidence to capture

- Notification ID, template/version, recipient role, channel, timestamps, delivery status/attempts and provider message ID.
- Contact metadata (channel, `verified`, `opt_in`, workspace match) with addresses and message bodies redacted.
- Audit export for the incident window:
  ```bash
  ./scripts/export-audit.sh --from YYYY-MM-DD --to YYYY-MM-DD --action notifications.queued --out /tmp/notifications-queued.json
  ./scripts/export-audit.sh --from YYYY-MM-DD --to YYYY-MM-DD --action notifications.dispatch --out /tmp/notifications-dispatch.json
  ./scripts/export-audit.sh --from YYYY-MM-DD --to YYYY-MM-DD --action notifications.contact_upserted --out /tmp/notifications-contacts.json
  ./scripts/export-audit.sh --from YYYY-MM-DD --to YYYY-MM-DD --action admin.feature_flag_changed --out /tmp/notifications-flags.json
  ```
- Provider ticket IDs, recall attempts and provider confirmations; approvals for corrective contact.
- No message bodies, addresses, patient names or clinical content in tickets or chat.

## Drill

A quarterly drill is required using synthetic subjects and contacts only. Exercise an unverified email, an opted-out patient Slack contact, a wrong-workspace contact, quiet hours and a disabled channel; confirm each is `suppressed` and that no provider message is sent. Include a simulated wrong-recipient report and measure time to stop the worker. **No drill record exists yet; this runbook has not been exercised.**

## Escalation

Security/compliance immediately for PHI, clinical detail or a wrong-patient send; clinical owner for patient-facing harm and corrective wording; E4 for provider adapters and Slack workspace administration; E2 for worker/queue state; engineering lead for the client-notification decision in [incident-response.md](./incident-response.md). Follow the client's privacy-incident process; never delete evidence to close a ticket.
