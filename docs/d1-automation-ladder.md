# D1 — Automation ladder

| Field | Value |
|---|---|
| Artefact | Discovery D1 |
| Gate | G0 |
| Owner | engineering lead |
| Date | 2026-11-02 |
| Related | [spec.md](./spec.md) · [architecture.md](./architecture.md) · [plan.md](./plan.md) |

Every client-facing task sits on exactly one rung. The **four answers** recorded for each task are:

1. **Why this rung** — why not the rung above or below.
2. **What the machine does** — deterministic code, LLM call, agent graph, or nothing.
3. **What a human must still do** — the non-negotiable human action.
4. **Failure mode** — what happens when the automation is wrong or unavailable.

## Rungs

| Rung | Meaning |
|---|---|
| **Code** | Deterministic rules, SQL, schemas, validators — no model |
| **LLM** | Single-purpose model call (classify, draft, embed, transcribe) behind LiteLLM |
| **Agentic** | Multi-step LangGraph + MCP tools with interrupts and provenance |
| **Human** | Named person must act; machine may prepare but cannot complete |

---

## Twelve client tasks

| ID | Task | Rung | 1. Why this rung | 2. Machine does | 3. Human must | 4. Failure mode |
|---|---|---|---|---|---|---|
| C-01 | Red-flag / emergency triage stop | **Code** | Missed red flag harms patient; must not depend on a model | Evaluate `config/red_flags.yaml` before any LLM; fail closed | Patient follows emergency guidance; front desk owns hand-off | Rules still run if LLM down; booking blocked |
| C-02 | Routine specialty match | **LLM** | Needs language understanding beyond closed keywords | Purpose alias for triage/specialty; OpenDecider second pass advisory | Patient confirms specialty if confidence low | Clarifying question → front-desk hand-off after second low confidence |
| C-03 | Doctor shortlist + free slots | **Agentic** | Multi-tool orchestration (search doctors, list slots) with UI cards | W1 graph + MCP scheduling tools; cards from tool truth | Patient chooses a card | Empty shortlist → hand-off; never invent a doctor |
| C-04 | Hold and confirm appointment | **Agentic** | Needs durable interrupt, idempotency and slot uniqueness | Soft-hold TTL, `interrupt()`, confirm API, unique active slot | Patient (or front desk) confirms | Hold expires; double-book blocked by DB constraint |
| C-05 | Cancel / reschedule appointment | **Code** + **Human** | Policy and identity are server rules; patient intent is human | Enforce ownership, policy windows, audit | Patient or front desk initiates | Reject out-of-policy; keep prior appointment |
| C-06 | Upload clinical document | **Code** | Bytes, malware, type sniffing are not LLM work | Type/size caps, ClamAV when configured, extract/chunk/embed pipeline | Patient/caregiver uploads; doctor may attach | Quarantine / reject; never silent accept |
| C-07 | Ask a cited question on my record | **Agentic** | Retrieval + draft + citation resolution across tools | W2 ask graph, SQL patient filter, provenance resolver | Patient reads answer; may send to review | Refuse if ungrounded / foreign chunk; zero scope leaks |
| C-08 | Caregiver access under consent | **Code** + **Human** | Consent is a legal act | Consent rows, `X-Consent-Id`, expiry/revoke | Patient grants/revokes; caregiver activates context | Expired consent → 404/deny; no token-claim substitute |
| C-09 | Consultation scribe draft (SOAP) | **Agentic** | Multi-step local draft with grounding and stock checks | W3 graph, local STT or uploaded transcript, local_main | **Doctor edits and signs** | Draft never auto-persists as note; unsigned invisible to patient |
| C-10 | Sign clinical note | **Human** | Clinical effect requires named clinician | Prepare draft + audit scaffolding only | Doctor signs (or rejects/edits) | Unsigned drafts stay in graph state |
| C-11 | Booking / hand-off notifications | **Code** | Templates must not invent clinical content | In-app record + email/Slack adapters; allowlists | Staff act on hand-off queue | Channel `unconfigured`/failed; booking still valid |
| C-12 | Admin cost / analytics review | **Code** + **LLM** | Aggregates are SQL; insights are advisory LLM | Snapshots, FinOps rollups, optional insight draft | Admin/compliance accept/reject insights | Insight cannot change config/budget/clinical behaviour |

---

## Six+ pod-found tasks

| ID | Task | Rung | 1. Why this rung | 2. Machine does | 3. Human must | 4. Failure mode |
|---|---|---|---|---|---|---|
| P-01 | PII/PHI egress gate | **Code** (+ local models as detectors) | Safety control cannot be a prompt | Composite PII engine + tokenisation; fail closed | Security enables egress only after sign-off | External path blocked; local fallback |
| P-02 | Cross-patient IDOR / scope guard | **Code** | Authorization is not an LLM skill | Server-derived patient context; SQL predicates | — | 404 + audit; red-team corpus |
| P-03 | Feature-flag / safety lock | **Code** | Safety flags must be immutable at runtime | Typed registry, startup validation | Admin changes non-safety flags with audit | Unknown/expired/unsafe flag → not ready |
| P-04 | Load-test abort vs real users | **Code** | Synthetic traffic must not harm live users | Traffic class, cohort tags, SLO abort guard | Ops starts/stops run | Abort on real-user guard trip |
| P-05 | Malware scan on upload | **Code** | Binary threat detection is AV, not LLM | ClamAV when `full` profile configures it | Ops keeps scanner healthy | Fail closed / quarantine |
| P-06 | Eval judge scoring | **LLM** | Comparative scoring needs a model | RAGAS/DeepEval via `EvalRunner` | Human calibration before judge trusted (κ≥0.6) | Judge labelled `unreviewed`; cannot waive safety |
| P-07 | Pharmacy stock check in draft | **Code** | Stock CSV truth must not be hallucinated | `check_stock` MCP + stale flags | Pharmacist/doctor interprets substitution | Stale/unknown → block substitution claim |
| P-08 | External partner MCP (R3) | **Agentic** (off by default) | Partner tools need broker isolation | Isolated read-only server, signed context, kill switch | Partner + security approve enablement | Remains unreachable until flag + ADR-19 |

---

## Ladder summary

| Rung | Client | Team | Rationale |
|---|---:|---:|---|
| Code | 4 primary (C-01, C-05*, C-06, C-11) | P-01…P-05, P-07 | Safety, authz, bytes, money aggregates |
| LLM | C-02, C-12* | P-06 | Single-purpose language / scoring |
| Agentic | C-03, C-04, C-07, C-09 | P-08 | Multi-tool workflows with interrupts |
| Human | C-08*, C-10 | — | Consent grant; clinical signature |

\*Split-rung tasks list both contributing rungs; the **completing** rung is Human where noted.

**Acceptance.** Eighteen tasks (≥12 client + ≥6 pod), each with one primary rung and the four answers — meets D1.
