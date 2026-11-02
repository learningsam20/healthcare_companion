# Escalations / emergency handoff SLA

## Purpose

When chat triage detects a red flag, Sahyog opens a `handoffs` row with a **2-minute** `sla_due_at`, notifies staff (in-app + Slack/email when configured), and surfaces the ticket on `/escalations`.

## Who is paged

- Recipient subject: `NOTIFY_OPS_SUBJECT` (same ops recipient as FinOps/ops alerts).
- Template: `staff_handoff` (in-app + `slack_staff` + email when channel adapters are configured).
- If `NOTIFY_OPS_SUBJECT` is empty, delivery_status stays `skipped` and Escalations still shows the ticket — configure the subject before claiming live paging.

## Overdue path

1. ARQ cron `handoff_sla_job` every minute marks open/assigned tickets past `sla_due_at`.
2. Sends `ops_alert` to the same ops subject.
3. Prometheus gauge `sahyog_handoffs_open{overdue="true"}` feeds Alertmanager rule `SahyogHandoffOverdue`.

## Operator steps

1. Open `/escalations` (or `/front-desk` → Escalations).
2. Filter **Overdue only** if needed; assign to yourself; call the patient / desk per clinic protocol.
3. Resolve with notes. Resolving clears SLA pressure for that ticket.

## Honesty

Mailpit / demo SMTP and unverified Slack maps are **not** production on-call. Real MTTA evidence remains under G-25 external residual.
