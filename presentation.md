# Sahyog Care Companion

## The Client

- Sahyog Health Network
  - Multi-site outpatient clinic network
  - Clinics such as Baner and Kothrud in the pilot geography
  - High phone booking load and large PDF report volume
- Day-to-day care teams
  - Patients booking care and reading their own records
  - Doctors writing and signing consultation notes
  - Front desk managing appointments and waitlists
  - Caregivers acting under explicit consent
  - Compliance and admin operators governing safety and cost
- What they need from a care companion
  - Triage and booking without drowning the phone lines
  - Cited answers over patient-owned documents
  - Faster note drafting with human sign-off
  - Auditable AI that keeps identified health data inside the clinic boundary

## The Problem

- Access and booking friction
  - Patients struggle to find the right doctor and open slot
  - Front desk absorbs repetitive intake and reschedule calls
  - Waitlist and no-show handling is manual and inconsistent
- Clinical documentation burden
  - Doctors spend significant time typing SOAP-style notes
  - Drafts risk inventing medicines or losing grounding in the visit transcript
  - Stock availability is checked late or outside the note flow
- Records are hard to use safely
  - PDFs and visit summaries sit unread or unsearchable
  - Answers without citations create clinical and legal risk
  - Caregiver access must respect consent, not informal sharing
- Safety and governance gaps for AI
  - Red-flag symptoms need deterministic fail-closed handling before a model replies
  - Identified PHI must not leak to logs, traces, or external model providers
  - Missing adapters must not silently “fake” success
- Operations blind spots
  - Hard to see adoption, hand-off MTTA, model spend, and egress posture in one place
  - Traces, metrics, and budgets are needed for trust before any wider rollout

## The Solution

- Role-scoped care companion on real identity
  - Keycloak OIDC for every environment and persona
  - Server-derived roles for patient, doctor, front desk, caregiver, pharmacist, compliance, and admin
- Guided clinical workflows
  - Find-my-doctor triage with deterministic red-flag rules before the model
  - Public-API booking, waitlist, and front-desk grids
  - Records upload, malware scan, chunking, embeddings, and ask-with-citations
  - Consultation scribe: transcript → grounded draft → edit / reject / **sign**
  - Stock-aware medicine lines and clinic stock reservation against a signed note
- Platform controls that stay honest
  - Composite PII gate; egress off by default; no PHI in logs or Langfuse content
  - MCP tool boundary with signed context; LiteLLM aliases by purpose
  - In-app notifications as source of truth; email and Slack staff delivery when configured
  - Unconfigured channels show as unconfigured — never silent mocks
- Operable demonstration stack
  - Analytics and FinOps with versioned metrics, showback, and budgets
  - Ops console for sessions, runs, MTTA, and deep links into Langfuse, Grafana, and Prometheus
  - Synthetic demo personas (Priya, Dr. Rao, Imran, Meera/Meena, Rita, ops) on sample data only

## The Benefits

- Patients and caregivers
  - Faster path from symptom description to a real booked slot
  - Clear answers from their own records with visible sources
  - Caregiver access only when consent is active
- Clinicians
  - Less typing time via grounded scribe drafts they still own at signature
  - Medicine lines checked against clinic stock before fulfillment hand-off
  - Less context switching across chat, notes, and appointments
- Front desk and clinic operations
  - Fewer routine phone cycles for booking and confirmation
  - Structured waitlist and appointment grids instead of ad-hoc spreadsheets
  - Staff notifications that route hand-offs without pasting clinical detail into email bodies
- Compliance and leadership
  - Auditable AI paths with humans in the loop
  - PHI kept inside the deployment boundary; external models only on de-identified text when enabled
  - Visibility into adoption, quality signals, cost, and safety posture before scale
- Network outcomes
  - Proof that agent workflows can support a multi-clinic outpatient network without claiming medical-device clearance
  - A foundation to extend sites, specialties, and channels with the same identity, safety, and FinOps rails

## The Roadmap

- Committed baseline, in order
  - R1 — Core companion: identity, chat, triage and booking, cited records, consoles, consent and audit, en/hi/mr, analytics and FinOps
  - R2 — Clinical companion: grounded scribe, local transcript, stock checks, clinician signature, expanded evals
  - R3 — Scale and extend: external MCP off by default, parallel ingest, load target, hybrid deployment boundary
- One extension proof inside the programme
  - X-01 nursing shift summary: one patient, one window, line-level citations, clinician accept / edit / reject
  - Draft workflow is in the pilot; a clinical-graded 20-case acceptance is still open
  - It is a reviewable draft, not a signed note and not an inpatient product
- How later work is chosen
  - One extension at a time, after a change order, an owner, and an ADR
  - Same safety gates as the baseline: citations, human sign-off, no identified data outside the clinic boundary
  - If only one follow-on is funded, finish full X-01 nursing notes first

## Future Work

- Next clinical and operational extensions
  - X-01 full: hospital-note ingestion, ward windows, and a larger cited-summary eval
  - X-02: vendor real-time pharmacy feed on the stock adapter that already exists
  - X-04: claims and coding assist, with a human coder in the loop
  - X-05 supervisor with specialists, or X-03 MCP productisation — not both at once
- Platform maturity after real usage
  - FinOps forecast calibration and, only with finance approval, chargeback
  - Production HA, row-level security, and clinical-text encryption
  - Production SMS/DLT onboarding, Slack on-call, and GPU / disaster-recovery sizing from measured load
- Longer horizon, each with its own trigger
  - ABDM / ABHA linking and FHIR write-back
  - Inpatient and ward workflows after full nursing notes
  - Telemedicine, wearables, and native mobile apps
  - A clinical validation programme — product attestation is not regulatory clearance
