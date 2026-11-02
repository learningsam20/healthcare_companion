# DPDP / subprocessor audit register (G-19)

**Status:** `not_attested` (no upload in this environment yet)

## What shipped in-repo

- Admin Governance → Compliance can upload a DPDP/subprocessor findings report (PDF/JSON/MD) and record named-approver attestation.
- Status values: `not_attested` | `pending` | `attested` | `disapproved` | `revoked`.
- When status is `disapproved`, or when `dpdp_enforce=true` without `attested`, patient-linked API prefixes return `403 dpdp_processing_stopped`. Privacy export/deletion and admin/meta remain available.
- Egress admin toggle still requires healthy composite PII **and** DPDP `attested` **and** `EXTERNAL_EGRESS_ENABLED` in the environment.

## What this is not

- Not a signed DPA.
- Not legal clearance to enable OpenRouter egress.
- `EXTERNAL_EGRESS` remains false until security sign-off.

## Evidence path

Runtime status: `GET /api/v1/admin/compliance` → `dpdp_audit`.
Public posture: `GET /api/v1/meta` → `capabilities.dpdp_audit_status` / `dpdp_processing_allowed`.
