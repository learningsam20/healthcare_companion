# D3 — Assumptions register

| Field | Value |
|---|---|
| Artefact | Discovery D3 |
| Gate | G0 / G2 |
| Owner | engineering lead (register); row owners below |
| Seed | [spec.md §11.2](./spec.md#112-assumption-register-seed-d3) |
| Fed by | [d2-discovery.md](./d2-discovery.md) |

| ID | Assumption | Owner | Validation | Fallback | Status |
|---|---|---|---|---|---|
| A-01 | OpenDecider improves intent/urgency and respects its trained prompt format | E1 | Compare on synthetic decision cases; MCP classify probes | Rules + small LLM; keep OpenDecider advisory | Mitigated — host Ollama present; keyword fallback labelled |
| A-02 | De-identified text is enough for W1/W2 quality; W3 can stay local | E1 / security | De-id vs identified eval on synthetic data; egress off by default | Keep identified workflows local; reduce external use | Accepted — `EXTERNAL_EGRESS` false until DPA |
| A-03 | Configured FHIR R4 demographics answers under 300 ms | E4 | Latency against sandbox/test server | Cache per session; manual lookup; mark stale | Mitigated — read adapter + SPA; write-back open |
| A-04 | Stock CSV is complete before clinics open; age known | E2 | File timestamp audit; stale threshold in config | Show stale/unknown; block substitution | Accepted — `config/stock.csv` + stale flags |
| A-05 | Doctors review drafts during the consultation | Clinical / E1 | Role-play consultations; review-time metric | Queue drafts for end-of-session review | Accepted by design — sign required |
| A-06 | One slot → one active appointment (no deliberate overbooking) | E2 | Unique partial index + concurrency tests | Model capacity per slot | Accepted — MC-19 tests |
| A-07 | LiteLLM MCP gateway can carry signed `_context` safely | E2 / E4 | Positive + negative tool tests | Opaque run-token registry; never drop scope guard | Accepted — broker verifies signature |
| A-08 | Postgres/pgvector fits Mac M4 Pro 26 GB with Compose services | E4 | Clean-machine start; memory under S profile | Move heavy models to host Ollama / larger host | Accepted for pilot profile P |
| A-09 | Local STT quality acceptable on synthetic audio | E4 | WER on non-PHI clips | Transcript upload; STT optional | Mitigated — EN WER measured; hi/mr residual |
| A-10 | Kaggle licences permit demonstration use | Data / compliance | Licence review on inventory | Use only fully permissive/generated data | Partial — 1 CC BY-NC-SA recorded; 4 `check_and_record` |
| A-11 | Keycloak runs in every acceptance environment including laptop | E2 | Setup smoke; no auth bypass | Reduce resource limits; minimal realm | Accepted |
| A-12 | Self-hosted Langfuse on Postgres accepts de-identified OTLP content | E2 | Resource check; payload privacy test | Local OTLP + Postgres traces; Langfuse optional | Accepted — content capture off |
| A-13 | 1,400 req/h peak is the binding scale target | engineering lead / product | Confirm volumes; load profiles | Re-run load; adjust sizing | Accepted as planning target; P-host capacity not claimed |
| A-14 | Separate staff/patient Slack workspaces and verified mappings exist for pilot | E4 | Allowlisted post + failure case | In-app/email only; Slack path disabled | Mitigated — staff proven; patient coverage residual |
| A-15 | Sizing inputs in `infra.md` confirmable before procurement | E4 / engineering lead | G0 input review; G5 measured load | Conservative ranges; phase GPU | Accepted as planning model |
| A-16 | Selected models handle hi/mr/Hinglish at required quality on pilot hardware | E1 / E4 | Language eval slice + latency on M4 | Stronger local or de-id external alias; record gap | Mitigated — gaps G-01/G-02/G-04 |

**Acceptance.** Sixteen rows (≥8), each with owner, validation and fallback — meets D3.
