# ADR-41: Sealed change request (day-8)

| Field | Value |
|---|---|
| ID | ADR-41 |
| Title | Sealed change — dual-audience Slack + all-role assistants in R1 |
| Status | **Accepted** (absorbed with trades) |
| Date decided | 2026-10-25 (same-day client message) |
| Owner | engineering lead |
| Process | [plan.md §10.3](../plan.md#103-sealed-change-request) |
| Related | `Q-07`, `Q-24`, `Q-31`, ADR-34, ADR-35, [changelog.md](../changelog.md) |

## Restatement (client-confirmed)

> “Slack must reach staff **and** opt-in patients with verified identities, and every application role — including compliance — needs a role-scoped assistant in the first release, not patient-only chat.”

## Impact

| Area | Impact |
|---|---|
| Scope | Dual Slack audiences; all-role chat/consoles; more AuthZ/notification tests |
| Data model | Verified Slack identity on contacts; `slack_audience`; notification delivery records |
| Architecture | Separate staff/patient workspace allowlists; cross-audience negative tests (T-21) |
| Eval set | Misdelivery / PHI-in-channel cases; role matrix expansions |
| i18n | Notification templates in en/hi/mr |
| Integrations | Real Slack adapter paths for both audiences; no channel-wide mention fallback |
| Plan | Absorbed into WP-06/11/14; eight-week baseline already assumed all R1–R3 (`PD-01`) |

## Three options

| Option | Cost | Outcome |
|---|---|---|
| **A — Absorb** | + notification/identity work; keep day-15 R1 candidate | Meets client ask; pressure on G4 notification evidence |
| B — Trade | Defer patient Slack to R2; keep staff-only | Faster R1; client rejects stated Q-24 answer |
| C — Defer post-handover | Patient Slack + compliance chat after G6 | Breaks `D-20` / Q-01 all-features commitment |

**Decision: Option A — Absorb**, with these trades (what moved / what was cut from the compressed path):

### What moved

- Patient Slack opt-in + verification into R1 notification design.
- Compliance console + role-scoped chat into R1 (not R2 stretch).
- Cross-audience red-team rows into D7 / eval set.
- Delivery calendar remains eight working weeks (already re-baselined).

### What was cut / deferred (explicit)

- Production chargeback (showback only) — `Q-23`, G-15.
- Claiming 100% verified patient Slack population at handover — G-07 residual.
- National ABDM certification and live write-back — G-09 / G-08.
- Blocking digest-pinned supply-chain CI — G-27 advisory until flip approved.

Mandatory checks were **not** removed.

## Same-day client message

```text
Subject: Day-8 change — confirmed absorb

We restated your change as: staff + opt-in patient Slack with verified IDs,
and role-scoped assistants for every app role including compliance in R1.

Decision (today): absorb into the current plan (Option A).
Trades (today): chargeback, ABDM certification, and “100% Slack coverage”
stay out of the acceptance claim; showback, stubs, and honest residuals
remain in gaps.md.

No mandatory safety check is waived. The steering review will show the ADR,
what moved, and what we cut.
```

## Revisit trigger

If the client later requires chargeback, ABDM certification, or guaranteed patient Slack coverage at acceptance, open a new ADR and re-plan; do not silently expand claims.
