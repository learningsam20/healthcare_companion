# Cost sheet

| Field | Value |
|---|---|
| Artefact | G5/G6 cost sheet |
| Price catalogue | [config/prices.yaml](../config/prices.yaml) `version: 1` |
| FinOps model | [config/finops_model.yaml](../config/finops_model.yaml) `2026-10-25.1` |
| Price basis date | **2026-10-25** |
| Accounting currency | USD |
| Display FX | **₹88 / US$** (`fx_usd_inr`) |
| Related | [infra.md](./infra.md) · evidence `finops-*.json` |

## 1. Cost lines (pack-aligned)

Drivers and formulae the team measures. Token assumptions below match this sheet’s illustrative profile (§3); replace with measured LiteLLM/FinOps averages when egress is on.

| Cost line | Driver the team measures | Formula | Source of the number |
|---|---|---|---|
| LLM tokens, triage (W1) | ~2k in / 400 out per triage turn (≈ up to six turns in a session) | `turns × (in×p_in + out×p_out)` | Traces; provider price list that day |
| LLM tokens, record answers (W2) | ~3k in / 500 out per answer | `answers × (in×p_in + out×p_out)` | Traces |
| LLM tokens, scribe (W3) | ~4k in / 800 out per draft | `notes × (in×p_in + out×p_out)` | Traces (local aliases price at $0) |
| Speech-to-text | ~8 minutes of audio per consultation | `minutes × p_minute` (or `hours × p_hour`) | Provider / local STT amortisation |
| Embeddings | New chunks/day × tokens per chunk | `tokens × p_token` | Ingest logs |
| Storage and compute | GB stored; worker / API hours | `GB×p_gb + hours×p_hour` | Cloud bill or on-prem amortisation ([infra.md](./infra.md)) |
| Queue / worker / LiteLLM opex | Worker hours, Redis, gateway | Included in infra envelope; alert on backlog | Compose/K8s metrics · FinOps |
| Interrupt wait time | Seconds a run waits on patient slot choice or doctor sign | Observed from checkpoint / review queue | Traces + review queue |
| Human review time | Doctor seconds per note | `(saved − spent) × loaded rate` | Role-play timings · edit-distance dashboard |
| **Cost per consultation / per run** | Bundle of the lines above for one visit | `triage + ask + scribe + notifications (+ STT if used)` | Cost meter per run; daily budget alert |

## 2. Formulae

```text
cost_usd(call) =
  (prompt_tokens  / 1e6) * input_per_million_usd(alias)
+ (completion_tokens / 1e6) * output_per_million_usd(alias)

stt_usd(hours) = hours * (local_per_audio_hour_usd | cloud_per_audio_hour_usd)

notification_usd =
  sms_segments * sms_per_segment_usd
+ emails * email_per_message_usd
+ (slack seats tracked outside app opex)

cost_per_consultation_usd ≈
  (triage_turns * avg_triage_cost)
+ (record_asks * avg_ask_cost)
+ (scribe_drafts * avg_scribe_cost)
+ (notifications_for_booking)
+ (stt_minutes * p_minute)   # when STT used

monthly_run_rate_usd ≈ observed_period_cost * (30 / period_days)
```

Local aliases (`local_main`, `local_small`, `local_embedding`, `local_draft`, local STT) price at **$0** token rates; electricity/amortisation sit in infra opex ([infra.md](./infra.md)), not per-token lines.

## 3. Unit prices (effective 2026-10-25)

| Item | USD | Note |
|---|---:|---|
| `local_*` input/output per 1M tokens | 0 | Host power in BoM |
| `external_reasoning` / `external_judge` in | 0.15 / 1M | Planning; replace with invoice |
| `external_*` out | 0.60 / 1M | Planning |
| Cloud STT / audio hour | 0.36 | Disabled (`cloud_enabled: false`) |
| SMS / segment | 0.0045 | Optional channel |
| Email / message | 0.0004 | Mailpit in demo = $0 incurred |
| Slack seat / month | 0 in app | Client workspace |

Budgets (config): models **$250**/mo · infra **$50**/mo · notifications **$25**/mo.

## 4. Measured usage (demo evidence)

| Source | Period | Observed | Cost USD |
|---|---|---|---:|
| [finops-showback-20261025T063043Z.json](./evidence/finops-showback-20261025T063043Z.json) | ~24 h window | 4 calls · 1,126 prompt + 244 completion tokens (`local_small`/`local_main`) | **0.00** |
| [finops-reconciliation-20261025.json](./evidence/finops-reconciliation-20261025.json) | import stamp | Match rate **37.5%**; gateway/app both **$0** on local aliases | **0.00** gateway & app |

Pilot host keeps `EXTERNAL_EGRESS_ENABLED=false`, so measured token cost stays **$0** while local models run. External unit prices apply only when de-identified egress is enabled after legal/security sign-off (G-19).

### Illustrative per-workflow cost (if egress were on at catalogue rates)

Assumptions: ~2k in / 400 out tokens per triage turn; ~3k / 500 per record ask; ~4k / 800 per scribe draft; 40% external share from FinOps profile P.

| Workflow | Est. external share cost USD | At ₹88 |
|---|---:|---:|
| W1 triage turn | ≈ 0.00022 | ≈ ₹0.02 |
| W2 record ask | ≈ 0.00030 | ≈ ₹0.03 |
| W3 scribe draft | ≈ 0.00043 | ≈ ₹0.04 |
| **Consultation bundle** (1+1+1) | ≈ **0.00095** | ≈ **₹0.08** |

These are **catalogue illustrations**, not invoices. Replace with measured LiteLLM spend after egress is approved.

## 5. Infra envelope (profile P — laptop pilot)

From `finops_model.yaml` / [infra.md](./infra.md):

| Line | Range |
|---|---|
| Capex incremental | ₹0 (owned Mac) |
| Opex / month | ₹6,300 – ₹25,000 |
| Cloud-equivalent opex / month | ₹26,000 – ₹75,000 |
| 3-year TCO | ₹2.3 – ₹9.0 lakh (excl. optional replacement) |

## 6. Honesty

- Demo measured cost is **$0** because traffic is local-priced.
- Do not claim production unit economics from P-host showback alone.
- Price basis date must be refreshed when vendor quotes land.
