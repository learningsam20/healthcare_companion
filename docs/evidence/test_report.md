# Performance & non-functional test report

Authoritative matrix for **volume**, **service times**, and **response times** from [spec.md](../spec.md) §6.1 / §8.3 and MC-18/MC-19.  
Companion load rollup: [load_test_report.md](./load_test_report.md). Demo narrative: [demo.md](../demo.md) §7.

> **Evidence naming.** Load-driver artifacts use the `load_test_*` prefix (`load_test_r1_matched_*.json`, `load_test_report.md`, etc.).

> **Honesty rule.** Duration below the preferred morning window (≥ 60 min) proves matched **rate / latency / error** on this host, not production capacity. `capacity_accepted=true` requires a **passing M/L host** run (G-17). P-host evidence must not be labelled as clinic capacity.

**Stamp:** `20261102T004206Z` · Host profile **P** · Stack: Docker API `:5706`, Keycloak, LiteLLM, MCP broker (`tev1:0.8b` decider), Ollama `qwen2.5:3b`, Prometheus `:5722`.

---

## 1. Required profiles (inputs that must match the NFRs)

| Profile | Request volume | Burst | Window | Simulated users | Host claim |
|---|---|---|---|---|---|
| R1 / R2 demo | **500 req/h** | 1× | Prefer **≥ 60 min** | Tagged `loadtest.*` Keycloak cohort (synthetic) | P/S evidence only |
| R3 pilot peak | **1,400 req/h** | **4×** (first ~10% of window) | Prefer **≥ 60 min** | Same cohort; public API + Keycloak only | `capacity_accepted` only on **M/L** |
| Data estate (NFR-SCALE-02) | 9,000 appts/day · 480k slots · 60k chunks · 500 doctors · 2,000 PDFs | — | Seed / generate | Synthetic rows only | Full counts are a **sizing target**, not the default sample seed |

**How executed this confirmation run:**

```bash
STAMP=20261102T004206Z
.venv/bin/python scripts/nfr_grid_latency_probe.py --repeats 25 \
  --out docs/evidence/load_test_grid_latency_${STAMP}.json
.venv/bin/python scripts/workflow_latency_probe.py --samples 6 \
  --out docs/evidence/load_test_chat_latency_${STAMP}.json
.venv/bin/python scripts/load_test.py --profile r1 --host-profile P \
  --rate 500 --burst 1 --duration 10m --cohort-size 5 \
  --prometheus-url http://127.0.0.1:5722 \
  --summary docs/evidence/load_test_r1_matched_${STAMP}.json
.venv/bin/python scripts/load_test.py --profile r3 --host-profile P \
  --rate 1400 --burst 4 --duration 5m --cohort-size 5 \
  --prometheus-url http://127.0.0.1:5722 \
  --summary docs/evidence/load_test_r3_matched_${STAMP}.json
```

Driver: load-guard **excludes `admin.ops`** and the `loadtest.*` cohort from real-user counts. Grid probe uses patient token for `/records/*`.

---

## 2. NFR matrix — performance, scale, availability, reliability

| ID | Requirement | Target | Status | Measured / evidence |
|---|---|---|---|---|
| **NFR-PERF-01** | Triage turn latency | p95 **< 4 s** | **Pass** | `qwen2.5:3b` + `tev1:0.8b`: n=6, p95 **1216.7 ms** ([load_test_chat_latency_20261102T004206Z.json](./load_test_chat_latency_20261102T004206Z.json)). |
| **NFR-PERF-02** | Record-answer latency | p95 **< 8 s** | **Pass** | Indexed loadtest PDFs; n=6, p95 **161.8 ms** (same chat evidence). |
| **NFR-PERF-03** | Note-draft after transcript | p95 **< 20 s** | **Indicative pass (n=1)** | Scribe **6.23 s** ([langfuse-trace-scribe-20261025.json](./langfuse-trace-scribe-20261025.json)); multi-sample doctor-cohort probe not re-run. |
| **NFR-PERF-04** | Time to book routine appointment | Median **< 3 min** | **Not measured** | Needs instrumented Playwright/UX timings (MC-18 companion). |
| **NFR-PERF-05** | Form/list grid response | p95 **< 500 ms** | **Pass at seeded volume** | Grids p95 **9.0 ms**; records p95 **10.0 ms**; pharmacy p95 **17.5 ms** on 15k stock / 5k appts ([load_test_grid_latency_20261102T004206Z.json](./load_test_grid_latency_20261102T004206Z.json)). |
| **NFR-PERF-06** | Text-PDF → visible `indexed` | **< 60 s** | **Pass (this run)** | 10 docs indexed; counts in [load_test_scale_volume_20261102T004206Z.txt](./load_test_scale_volume_20261102T004206Z.txt). |
| **NFR-PERF-07** | Chat first token (warm) | p95 **< 2 s** | **Pass (completion proxy)** | Warm completion proxy n=6, p95 **178.0 ms** (same chat JSON); SSE `ttft` span still preferred for strict claim. |
| **NFR-PERF-08** | Analytics / FinOps queries | p95 **< 500 ms** | **Pass** | overview/finops p95 **17.8 ms** ([load_test_grid_latency_20261102T004206Z.json](./load_test_grid_latency_20261102T004206Z.json)). |
| **NFR-SCALE-01** | Peak API load | **1,400 req/h** + **4× burst**, error **< 1%** | **Pass (rate/latency on P; not capacity)** | R3: **1833.5 req/h**, err **0%**, p95 **50.9 ms**, 5m ([load_test_r3_matched_20261102T004206Z.json](./load_test_r3_matched_20261102T004206Z.json)). R1: **509.6 req/h**, err **0%**, p95 **57.9 ms**, 10m. `capacity_accepted=false` on P. |
| **NFR-SCALE-02** | Data volumes | See §1 | **Partial (pharmacy + appts + loadtest PDFs)** | stock_items **15,010**, appointments **5,040**, documents **12**, chunks **10**, patients **9** ([load_test_scale_volume_20261102T004206Z.txt](./load_test_scale_volume_20261102T004206Z.txt)). Not yet 480k slots / 2k PDFs / 60k chunks. |
| **NFR-SCALE-03** | Stateless API / checkpoint resume | Any replica | **Partial** | Checkpointer configured; dual-replica soak residual ([chat-interrupt-ha-soak-20261101T064947Z.json](./chat-interrupt-ha-soak-20261101T064947Z.json), G-46). |
| **NFR-AVAIL-01** | 99.5% clinic-hours availability | Pilot | **Not measured** | Needs monitoring window + SLO burn (G-25). |
| **NFR-AVAIL-02** | LLM down → red-flag + hand-off | Fail closed | **Mitigated in code** | Deterministic rules before model; gateway local/Ollama fallback for local aliases. |
| **NFR-REL-01** | Timeouts / backoff / breaker | No unbounded retry | **Partial** | Gateway + MCP timeouts; Keycloak token retries in load driver; dedicated fault-injection report incomplete. |
| **NFR-REL-02** | Checkpoint survives restart | Resume on other replica | **Partial** | Same as SCALE-03 / G-46. |
| **NFR-RECOV-01** | Restore ≤ 4 h; RPO 24 h | Restore drill | **Partial** | Encrypted backup evidence ([encrypted-backup-20261031T174501Z.json](./encrypted-backup-20261031T174501Z.json)); full empty-env restore residual (G-11). |
| **MC-18** | Perf + load + Keycloak cohort + guards | Profiles above | **Partial pass** | Matched R1/R3 + workflow p95 on P with Keycloak `loadtest.*`; kill-drill proven ([load_test_kill_drill_20261031T170411Z.json](./load_test_kill_drill_20261031T170411Z.json)). Residual: prefer ≥60m window + M/L `capacity_accepted`. |
| **MC-19** | Booking idempotency / ≤20 of 1,000 | Concurrency tests | **Unit/integration** | Not repeated inside the httpx volume driver. |

---

## 3. Response-time & service-time summary

### 3.1 API / grid response times (NFR-PERF-05, SCALE-01)

| Run | Rate | Duration | Requests | Actual req/h | Error % | p95 ms | Grid ≤500? | Evidence |
|---|---|---|---|---|---|---|---|---|
| R1 matched | **500** | **10 m** | 85 | **509.6** | **0.0** | **57.9** | **yes** | [load_test_r1_matched_20261102T004206Z.json](./load_test_r1_matched_20261102T004206Z.json) |
| R3 matched | **1400 ×4** | **5 m** | 153 | **1833.5** | **0.0** | **50.9** | **yes** | [load_test_r3_matched_20261102T004206Z.json](./load_test_r3_matched_20261102T004206Z.json) |
| Grid + pharmacy + analytics | — | 25× paths | 325 | — | **0** | grids **9.0** / pharmacy **17.5** / analytics **17.8** | **yes** | [load_test_grid_latency_20261102T004206Z.json](./load_test_grid_latency_20261102T004206Z.json) |

R1 matched per-endpoint p95 (all ≤ 500 ms):

| Endpoint | n | p50 ms | p95 ms |
|---|---|---|---|
| `/api/v1/appointments` | 14 | 25.5 | 55.6 |
| `/api/v1/chat/sessions` | 10 | 26.7 | 72.4 |
| `/api/v1/doctors` | 6 | 27.2 | 60.9 |
| `/api/v1/doctors/.../slots` | 8 | 21.2 | 49.7 |
| `/api/v1/patients` | 6 | 28.6 | 65.0 |
| `/api/v1/notifications` | 13 | 21.7 | 49.9 |
| `/api/v1/meta` | 10 | 21.4 | 26.4 |
| `/api/v1/records/documents` | 6 | 27.9 | 29.4 |
| `/api/v1/records/medications` | 5 | 17.5 | 56.4 |
| `/api/v1/me/memory` | 7 | 24.5 | 64.2 |

### 3.2 Workflow service times (NFR-PERF-01/02/03/07)

| Workflow | Target | This stamp | Verdict |
|---|---|---|---|
| W1 triage turn | p95 < 4 s | n=6, p95 **1216.7 ms** (`tev1:0.8b` + `qwen2.5:3b`) | **Pass** |
| W2 record ask | p95 < 8 s | n=6, p95 **161.8 ms** (indexed loadtest PDFs) | **Pass** |
| W3 draft | p95 < 20 s | Langfuse scribe **6.23 s** (n=1) | Indicative pass |
| Chat TTFT | p95 < 2 s | Warm completion proxy n=6, p95 **178.0 ms** | **Pass (proxy)** |
| Book UX | median < 3 min | — | Open — Playwright |

### 3.3 Analytics (NFR-PERF-08)

| Endpoint | n | p50 ms | p95 ms | Meet ≤500? |
|---|---|---|---|---|
| `/api/v1/analytics/overview` | 25 | 16.2 | 17.8 | **yes** |
| `/api/v1/analytics/finops` | 25 | 7.6 | 8.7 | **yes** |

### 3.4 Eval / AI quality (release-adjacent)

| Suite | Headline | Evidence |
|---|---|---|
| Deterministic W1 | **30/30** pass · red-flag recall **1.0** · FP **0.0** | [eval-w1-deterministic-20261101T170120Z.json](./eval-w1-deterministic-20261101T170120Z.json) |
| Deterministic W2 | **30/30** pass · provenance integrity **1.0** | [eval-w2-deterministic-20261101T170120Z.json](./eval-w2-deterministic-20261101T170120Z.json) |
| RAGAS / DeepEval (prior) | Faithfulness / relevancy as previously recorded | [eval-ragas-w3-20261025T083908Z.json](./eval-ragas-w3-20261025T083908Z.json), [eval-deepeval-x01-20261025T095159Z.json](./eval-deepeval-x01-20261025T095159Z.json) |
| Judge calibration | Unreviewed (G-16) | Do not claim clinical-quality sign-off |

### 3.5 Smoke / functional companion

| Check | Result |
|---|---|
| API liveness / readiness | Pass |
| Analytics tiles / compliance / audit grid | Pass (`audit.grid` total=11713) |
| `provenance.types` (chat source panel) | Prior fail during stack bounce; chat graph healthy on this stamp (PERF-01/02/07 pass) — smoke not re-run |
| Evidence log | [smoke-nfr-20261101T170120Z.txt](./smoke-nfr-20261101T170120Z.txt) (from `/tmp/sahyog-nfr/smoke2.log`) |

### 3.6 Guard / recovery companion

| Item | Result | Evidence |
|---|---|---|
| Load abort kill drill (G-22) | `budget_guard` observed | [load_test_kill_drill_20261031T170411Z.json](./load_test_kill_drill_20261031T170411Z.json) |
| Encrypted backup | Present | [encrypted-backup-20261031T174501Z.json](./encrypted-backup-20261031T174501Z.json) |
| Chat interrupt HA soak | Residual | [chat-interrupt-ha-soak-20261101T064947Z.json](./chat-interrupt-ha-soak-20261101T064947Z.json) |

---

## 4. Volume — simulated users & data estate

| Input | Spec | This environment |
|---|---|---|
| Load identities | Dedicated `loadtest.*` | **5 patients + 5 front desk** (`cohort-size 5`); admin.ops excluded from real-user guard counts |
| Traffic class | `synthetic` | Enforced on cohort (`/auth/me.traffic_class`) |
| Request rate R1 | 500 / h | Observed **509.6** over 10 m |
| Request rate R3 | 1400 / h + 4× burst | Observed **1833.5** over 5 m |
| Patients / appts / PDFs / chunks | SCALE-02 targets | **Partial** — 9 patients / 5,040 appts / 15,010 stock / 12 docs / 10 chunks; not 480k slots / 2k PDFs |

---

## 5. Observability used for this report

| System | Role | Status |
|---|---|---|
| Prometheus `:5722` | Scrape `sahyog-api` (+ host job when `--local`) | Up during matched runs |
| Grafana `:5723` | Dashboards | Available on full profile |
| Langfuse | Agent span latencies | Prior traces cited; live workflow spans not collected this stamp |
| Load-guard API | Real-vs-synthetic / budget | Healthy; 0 real_events during matched R1/R3 |

---

## 6. Volume honesty — grids, pharmacy, chat, PERF-02, SCALE-02

### 6.1 Do grids (incl. pharmacy search) have enough volume?

**Partial.** This stamp has **15,010** `stock_items`, **5,040** appointments, and grid/pharmacy p95 well under 500 ms ([load_test_grid_latency_20261102T004206Z.json](./load_test_grid_latency_20261102T004206Z.json)). That is enough for a seeded PERF-05 claim on this estate, **not** a SCALE-02 claim (480k slots / 2k PDFs / 60k chunks still absent).

### 6.2 Chat latency (PERF-01/02/07)

Healthy on this stamp with `tev1:0.8b` + `qwen2.5:3b`: triage p95 **1216.7 ms**, record-ask **161.8 ms**, warm completion proxy **178.0 ms** ([load_test_chat_latency_20261102T004206Z.json](./load_test_chat_latency_20261102T004206Z.json)). Earlier HTTP 500s were from DB pool bounce, not model budget. Strict PERF-07 still prefers SSE `ttft` spans.

### 6.3 PERF-02 — loadtest PDFs

Indexed loadtest PDFs are present (`docs_indexed=10`); W2 record-ask passed. To grow further:

```bash
./scripts/generate-synthetic.sh --patient-cohort loadtest --pdfs 10 --doctors 0 --slots 0 --ingest
```

### 6.4 SCALE-02 — full estate still staged

Caps/calendar support SCALE-02 targets; full 500×480k×2k remains a long M/L job:

```bash
./scripts/generate-synthetic.sh --doctors 50 --slots 5000 --pdfs 50 --patient-cohort both --ingest
./scripts/generate-synthetic.sh --doctors 500 --slots 480000 --pdfs 2000 --patient-cohort both --ingest
```

---

## 7. Gaps before signing MC-18 / G-17

1. Prefer **≥ 60 m** R1 + R3 JSON (10 m / 5 m here match **rate/latency/error** only on P).
2. Multi-sample doctor scribe for PERF-03; Playwright booking median (PERF-04).
3. Full SCALE-02 generate, then re-measure grids at that volume.
4. M/L host run with `capacity_accepted=true` (G-17).
5. AVAIL-01 monitoring window; full restore drill (RECOV-01 / G-11).

---

## 8. Change log

| Date | Change |
|---|---|
| 2026-11-01 | Created matrix; Prometheus host scrape; per-endpoint NFR slices in load driver. |
| 2026-11-01 (T170120Z) | Executed non-load NFRs (grid/analytics, deterministic W1/W2, smoke, scale counts) + matched R1 10m / R3 5m on P; workflow probe failed on chat 500; refreshed this report + `load_test_report.md`. Load driver excludes admin.ops from real-user guard counts. |
| 2026-11-02 | Renamed load evidence to `load_test_*` / `load_test_report.md`. Raised `generate-synthetic` to SCALE-02 caps + `--patient-cohort loadtest` for PERF-02; extended slot calendar; pharmacy paths added to grid probe. Documented volume honesty in §6. |
| 2026-11-02 (T000825Z) | Decider → `tev1:0.8b`; S3Proxy checksum fix; loadtest PDFs indexed; re-ran grids/pharmacy, R1 10m, R3 5m, chat PERF-01/02/07 — all passed on P (`capacity_accepted=false`). Volumes: 15,010 stock / 5,040 appts / 12 docs. |
| 2026-11-02 (volume) | Kaggle medicines → `load_test_pharmacy_stock.csv` (15k imported); healthcare doctors → appointments (5k); scripts `load_test_prepare_datasets.py` / `load_test_seed_volume.py` / `load_test_setup.sh`; renamed `load_test.sh` (+ wrappers); chat aliases → qwen2.5:3b; grid+pharmacy+R1 volume evidence refreshed. |
| 2026-11-02 (T004206Z) | Confirmation suite: grids (patient records auth fix, 0 errors), chat PERF-01/02/07, R1 10m, R3 5m — all **passed** on P. |
