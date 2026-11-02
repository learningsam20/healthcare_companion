# ABDM stub equality matrix

**Status:** local path stub only. `certified: false` on every response. This is **not**
ABDM sandbox credentials, Health Tech Committee approval, or national certification.

## How to get real sandbox access (human / NHA)

1. Apply at https://sandbox.abdm.gov.in/sandbox/v3/
2. Wait for Health Tech Committee approval (semi-manual; one application).
3. Collect `clientId` / `clientSecret` from the sandbox portal.
4. Register a public bridge callback URL (`PATCH …/gateway/v3/bridge/url`).
5. Call gateway `https://dev.abdm.gov.in` with `X-CM-ID: sbx`; ABHA at
   `https://abhasbx.abdm.gov.in/abha/api/v3/`.
6. Link the facility on sandbox HFR; complete milestones, functional test, security
   audit, and HTC demo before production.

Until then, point `ABDM_SANDBOX_URL` at the local stub (`http://abdm-stub:8090`).

## Equality matrix

| Official family (docs.abdm.gov.in) | Stub path (same shape) | Hospital seam mapping | Equality note |
| --- | --- | --- | --- |
| Gateway session | `POST /api/hiecm/gateway/v3/sessions` | Used by stub health/session smoke; hospital `/api/v1/abdm/status` polls stub `/health` | Path equal; token is fake |
| Bridge URL | `PATCH/GET /api/hiecm/gateway/v3/bridge/url` | No hospital UI; ops only | Path equal; stores URL in memory |
| Bridge certs | `PATCH /api/hiecm/gateway/v3/bridge/certs` | None | Path equal; stores payload |
| ABHA enrollment OTP | `POST /abha/api/v3/enrollment/request/otp` | Future: link flow may request OTP via stub | Path equal; no Aadhaar |
| ABHA enrol | `POST /abha/api/v3/enrollment/enrol/byAadhaar` (and byDocument) | Maps to opaque `patient_external_ids` via `PUT /api/v1/abdm/patients/{id}/link` | Path equal; ABHA number invented |
| ABHA login OTP / verify | `POST /abha/api/v3/profile/login/request/otp`, `…/verify` | Same opaque link store | Path equal |
| ABHA profile | `GET /abha/api/v3/profile/account` | Status only | Path equal; fixed stub profile |
| HIP care-context link | `POST /api/hiecm/hip/v3/link/carecontext` | Not exposed on hospital API yet | Path equal; ACK only |
| HIP callbacks | `POST /api/v3/hip/...` | Bridge callback target for local tunnel tests | Path equal; echo ACK |
| HIU consent init/status | `POST /api/hiecm/consent/v3/request/init`, `GET …/status/{id}` | Not exposed on hospital API yet | Path equal |
| HIU callbacks | `POST /api/v3/hiu/consent/request/{on-init,notify}` | Bridge callback target | Path equal; echo ACK |
| Hospital identity seam | n/a (Sahyog product API) | `/api/v1/abdm/*` | **Not** an ABDM official path; stores `sha256:…\|last4:…` only |

## What is deliberately unequal

- No real JWT validation against NHA.
- No Aadhaar/OTP delivery.
- No HFR facility registry.
- No FHIR bundle exchange.
- Hospital routes stay under `/api/v1/abdm/*` so product code does not pretend to be the gateway.

Machine-readable index: `GET {ABDM_SANDBOX_URL}/stub/equality`.
