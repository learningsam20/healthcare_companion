# MTTA and staff paging (G-25 residual)

## What ships

- Emergency chat red-flags create a handoff with `sla_due_at = now + 2 minutes`.
- Staff notify uses template `staff_handoff` on **in-app + email + Slack staff** when:
  - `NOTIFY_SEND_EXTERNAL=true`
  - `NOTIFY_OPS_SUBJECT` is a Keycloak subject with **verified** `email` and `slack_staff` contacts
  - SMTP and Slack staff adapters are configured
- Escalations UI shows SLA countdown / OVERDUE; cron `handoff_sla_job` + alert `SahyogHandoffOverdue` fire when overdue.
- Demo path: Mailpit captures SMTP locally; Alertmanager drills are recorded under `docs/evidence/`.

## What MTTA means here

**MTTA (mean time to acknowledge)** is an *operations* metric: time from handoff create → first human assign/ack on `/escalations`.

This build **does not claim a production MTTA SLO**. Recording MTTA requires:

1. A real on-call rota (not Mailpit-only demo sink for paging).
2. A population of production incidents over a window.
3. An owner-signed MTTA target (e.g. ≤2 minutes to assign for emergency).

Until then, treat the product SLA as:

| Signal | Product behaviour | Ops claim |
|---|---|---|
| Ticket created | Always (even if notify skipped) | Visible on Escalations |
| Staff email/Slack | When adapters + `NOTIFY_OPS_SUBJECT` configured | Delivery probe evidence closes **channel** readiness, not MTTA |
| Overdue | UI badge + metric/alert | Needs human response to clear |

## Operator checklist (pilot)

1. Set `NOTIFY_OPS_SUBJECT` to `frontdesk.imran` (or duty subject) after `./scripts/seed-users.sh` / contact mapping.
2. Confirm `/api/v1/meta` shows `email` and `slack_staff` as `configured`.
3. Run `scripts/probe_notify_channels.py --write-evidence` and keep the JSON under `docs/evidence/`.
4. Open `/escalations`, trigger a red-flag chat, confirm ticket + Slack/email arrive within seconds.
5. Document any drill MTTA in the incident notes; do **not** update gaps.md to Closed for G-25 without that ops evidence.

## Honest residual

**G-25 stays Mitigated** until production paging + measured MTTA exist. Everything above is sufficient for a **supervised pilot ship** with this caveat listed explicitly.
