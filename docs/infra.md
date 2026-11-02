# Infrastructure sizing, bill of materials and capex/opex

| Field | Value |
|---|---|
| Product | Sahyog Care Companion |
| Document | `docs/infra.md` — parameterized sizing, profiles, bill of materials, capex/opex/TCO, what-if and growth model |
| Version | 1.0 — implementation baseline |
| Date | 2026-10-25 |
| Status | Approved planning model. This is a sizing guide and an indicative bill of materials (BoM), **not a procurement quote**. Prices, tariffs and FX are planning assumptions to be replaced with vendor quotes and the client's finance rate before purchase. All amounts exclude GST and other taxes unless stated. |
| Owner | engineering lead with the client finance/procurement owner |
| Related documents | [spec.md](./spec.md) · [architecture.md](./architecture.md) · [plan.md](./plan.md) · [setup.md](./setup.md) · [roadmap.md](./roadmap.md) · [gaps.md](./gaps.md) |
| Shared runtime model | `config/finops_model.yaml` — the same versioned parameters, formulas and scenarios that power the FinOps what-if workspace (`ANL-AC-06`, `MC-33`) |

**Why this document exists.** [architecture.md §11.2](./architecture.md#112-capacity-and-sizing-reference) is the runtime view; this document turns it into a parameterized model. Change demand, retention, availability or hosting assumptions and recompute the infrastructure, capex and opex. It is also the bridge between the FinOps product capability (`FR-FIN`) and the total cost of owning the platform.

**How to use it:**

1. Fill the inputs in §2 with measured or contracted values. The defaults are planning values, not facts.
2. Compute resource quantities with §3.
3. Pick the closest profile in §4, then replace the indicative unit costs with quotes.
4. Use §7 for unit economics, profitability and the what-if/growth model that the product must expose.
5. Re-run at G0 (envelope), G1 (environment decision), G5 (measured load) and G6 (handover). A sizing model that is never re-run is a guess with a spreadsheet.

---

## 1. What drives size

| Driver | Unit | Why it matters |
|---|---|---|
| Peak API rate | requests/hour and burst factor | Sizes API replicas, rate limits, connection pools and LiteLLM/MCP concurrency. LLM turns hold a connection for seconds. |
| Concurrent chat/scribe/summary runs | active runs | Drives API memory, SSE buffers, model concurrency and queue capacity. |
| Document volume and pages | documents/month, pages/document | Drives object storage, ingestion queue, chunk count, pgvector index memory and backup size. |
| Audio volume | consultation hours/month | Drives STT compute, temporary object storage and deletion jobs; audio is deleted at 24 hours. |
| Model placement | external vs local share | External tokens are opex per token; local models need unified/GPU memory and have concurrency limits. |
| Purpose-specific routes | number of local aliases in use | Running several local models at once multiplies memory; one large model for everything is not the design (`D-24`). |
| Retention | days/months per data class | Drives Postgres, object storage, observability and backup growth. Audit (1 year) and notes (1 year in demo) are the large tails. |
| Availability | single host, N+1, multi-AZ | Doubles or triples app/DB/network cost; adds load balancers, WAF and standby capacity. |
| Observability | traces/metrics/log volume, retention | Langfuse (Postgres) and Prometheus/OTel are real compute/storage; content capture is off, but metadata is not free. |
| Notification volume | SMS segments, emails, Slack messages/month | Small compared with model cost, but SMS is the largest per-unit channel cost. |
| Hosting model | on-prem, colo, India cloud, hybrid | Shifts capex to opex; changes power, bandwidth, support, GPU availability and exit cost. |

The model is deliberately conservative on **concurrency**, not average RPS. A 1,400 requests/hour average is ~0.39 rps, but 50 simultaneous 8-second model turns is a different capacity problem.

---

## 2. Sizing inputs

These are the parameters the rest of the document uses. Replace them with measured values; defaults are for planning only.

| # | Parameter | Symbol | Demo/acceptance (S) | Laptop pilot (P) | Hosted pilot (M) | Production (L) | How to measure / source |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Registered users | `U` | 2,000 | 50 | 10,000 | 50,000 | Product/registration data |
| 2 | Monthly active users | `MAU` | 500 | 30 | 3,000 | 20,000 | Product analytics |
| 3 | Peak API requests/hour | `R` | 500 | 100 | 1,400 | 1,400 | Load profile (`NFR-SCALE-01`) |
| 4 | Burst factor | `b` | 4 | 2 | 4 | 4 | Load test profile |
| 5 | Concurrent chat/scribe/summary runs | `C` | 50 | 10 | 100 | 250 | Trace concurrency at peak |
| 6 | Appointments/day | `A_day` | 200 | 20 | 2,000 | 9,000 | Booking data |
| 7 | Documents/month | `D_m` | 500 | 50 | 2,000 | 10,000 | Upload data |
| 8 | Pages/document | `P_d` | 10 | 10 | 10 | 10 | Ingest data |
| 9 | Chunks/document | `K_d` | 40 | 40 | 40 | 40 | Chunking config |
| 10 | Existing/searchable chunks | `K` | 60,000 | 40,000 | 500,000 | 2,000,000 | `document_chunk` count |
| 11 | Audio hours/month | `H_a` | 20 | 10 | 200 | 1,000 | STT/encounter data |
| 12 | External LLM share | `E` | 60% | 40% | 40% | 20% | Routing policy/config |
| 13 | Average input tokens/turn | `T_in` | 2,000 | 2,500 | 3,000 | 3,000 | LiteLLM spend logs |
| 14 | Average output tokens/turn | `T_out` | 500 | 500 | 600 | 600 | LiteLLM spend logs |
| 15 | Chat turns/day | `N_turn` | 1,500 | 1,000 | 10,000 | 60,000 | Product analytics |
| 16 | SMS segments/month | `N_sms` | 1,000 | 100 | 10,000 | 80,000 | Notification delivery |
| 17 | Emails/month | `N_email` | 2,000 | 200 | 20,000 | 150,000 | Notification delivery |
| 18 | Slack messages/month | `N_slack` | 500 | 100 | 5,000 | 40,000 | Notification delivery |
| 19 | Chat/checkpoint retention | `Ret_chat` | 30 days | 30 days | 30 days | 30 days | Spec §6.5 |
| 20 | Audit/notes retention | `Ret_audit` | 1 year | 1 year | 1 year | 1 year+ | Client policy |
| 21 | Availability target | `HA` | Single host | Single laptop | N+1 app | Multi-AZ | `NFR-AVAIL-01`, client |
| 22 | Local model footprint | `LLM` | Optional 24 GB GPU | ≤7 GB unified | 1 × 48 GB GPU | 2 × 48 GB GPU | Model choice/Q-10, D-19 |
| 23 | Hosting | `Host` | Laptop or cloud VM | Owned Mac M4 Pro | On-prem/colo or cloud | India cloud/managed | `Q-25`, `Q-28` |
| 24 | FX rate | `FX` | ₹88/US$ | ₹88/US$ | ₹88/US$ | ₹88/US$ | Finance rate on purchase date |
| 25 | Power tariff | `P_kwh` | ₹9/kWh | ₹9/kWh | ₹9/kWh | ₹9/kWh | Site/utility contract |
| 26 | PUE (cooling/overhead) | `PUE` | 1.5 | 1.1 (laptop) | 1.5 | 1.5 | Site measurement |
| 27 | Support/ops loading | `Ops` | 0 | Owner-operated | 0.2 FTE | 0.5 FTE | Operating model |
| 28 | Model price catalogue | `Price` | `config/prices.yaml` v1 | same | same | same | Effective-dated catalogue |
| 29 | FinOps model version | `Model` | `finops-1.0` | same | same | same | `config/finops_model.yaml` |

**Sanity checks:**

- `R/3600` is average requests/second; the design must hold `R × b / 3600` for short bursts.
- `N_turn` is not `R`; one user turn can create several API requests and several model/tool calls.
- `K` grows with retention: `K ≈ K_initial + D_m × K_d × months_retained` for documents that are kept. Recompute after a retention change.
- The laptop pilot is a **pilot**, not an acceptance capacity claim. The S/M/L profiles carry acceptance, hosted-pilot and production claims respectively.
- Document/audio volumes are the largest uncertainty. If the client has historical volumes, use them instead of these defaults.

---

## 3. Sizing formulas

These formulas produce planning quantities, not benchmark guarantees. Round up and add the stated headroom.

### 3.1 API and worker compute

```text
rps_peak   = R / 3600
rps_burst  = R × b / 3600
vCPU_api   = max(2, ceil(rps_burst × cpu_s_per_request / 0.60))
replicas   = HA == single ? 1 : max(2, ceil(vCPU_api / 4))
RAM_api    = 2 GB × replicas + 1 GB headroom
```

`cpu_s_per_request` is CPU time, not wall-clock time; model waiting is not CPU. Use **0.02–0.05 CPU-seconds** for CRUD/grid/SSE orchestration until profiling replaces it. At R=1,400 and b=4, `rps_burst=1.56`; even 0.05 s gives <0.13 vCPU, so the minimum of 2 vCPU/replica dominates. The real driver is concurrency and memory for 250 open runs, not raw CPU.

```text
C_worker   = max(2, ceil(C / 4))       # ingest/STT/notify jobs are async
vCPU_worker = C_worker × 2
RAM_worker  = C_worker × 4 GB
```

Workers are bounded by concurrency and model/tool semaphores, not CPU count alone. OCR and STT are the CPU/GPU-heavy jobs; keep them on a separate queue with their own cap.

### 3.2 Model concurrency and memory

```text
turns_per_second = N_turn / 86400 × peak_share   # peak_share ≈ 0.25
C_model = max(C, turns_per_second × avg_turn_seconds)
local_share = 1 − E
C_local = C_model × local_share
```

Local memory planning:

```text
VRAM_min ≈ weights_GB × 1.2 + KV_cache_GB + 2 GB runtime
KV_cache_GB ≈ context_tokens × batch × bytes_per_token × layers_factor
```

Use measured memory, not a generic rule. A practical planning table:

| Local model purpose | Weights (Q4/Q8) | Minimum memory | Practical concurrent contexts (8k) | Use |
|---|---:|---:|---:|---|
| 7–8B instruct, Q4 | 5–7 GB | 16–24 GB GPU or unified | 4–8 | W3 draft, X-01 summary, insights |
| 7–8B instruct, Q8 | 8–10 GB | 24 GB | 3–6 | Higher-quality local path |
| 13B, Q4 | 8–10 GB | 24 GB | 2–4 | Only if quality requires it |
| 70B, Q4 | 38–45 GB | 48–80 GB | 1–2 | Not R1–R3 |
| Embeddings (`bge-m3`) | 2–3 GB | 8–16 GB CPU/unified | Batch | Ingest; can share with headroom |
| 3–4B instruct, Q4 | 2–3 GB | 8 GB | 4–8 | Titles/clarification |
| PII composite | 2–3 GB | 8 GB | Batch/stream | Presidio + GLiNER + optional filter |
| STT `small` int8 | 0.8–1.5 GB | 4 CPU cores | 1–2 streams | W3 local |

If `C_local` exceeds practical concurrency, queue with a bounded wait and fall back to the external de-identified route (if policy allows) or hand off. Do not claim a device can serve unlimited streams.

### 3.3 Postgres, vectors and Redis

```text
S_pg_text   ≈ 2 GB base + K × 6 KB + audit/event/usage growth
S_pg_vector ≈ K × dimensions × 4 bytes × 1.3 (HNSW overhead)
S_pg_total  ≈ S_pg_text + S_pg_vector + 30% working space
M_hnsw      ≈ K × dimensions × 4 bytes × 1.3
```

At 1,024 dimensions:

| `K` chunks | Vector/index estimate | Planning DB RAM |
|---:|---:|---:|
| 40,000 | ~0.2 GB | 4–8 GB (laptop cap) |
| 60,000 | ~0.3 GB | 8 GB |
| 500,000 | ~2.7 GB | 16–32 GB |
| 2,000,000 | ~10.6 GB | 64 GB |

`shared_buffers` is not the whole dataset; plan for cache hit rate and measure. HNSW build memory can exceed steady-state memory; schedule index builds in a maintenance window or use a read replica for the build. On the Mac pilot, `shared_buffers=1GB`, `work_mem=32MB`, `max_connections=100` ([architecture.md §6.7](./architecture.md#67-postgres-only-database-profile)).

```text
M_redis ≈ 256 MB + 50 KB × C + queue_backlog_headroom
M_redis_plan = max(1 GB, M_redis × 2)
```

Redis holds queues, rate limits, idempotency and ephemeral SSE buffers. SSE buffers are TTL-bound and not backed up; do not size Redis as a system of record.

### 3.4 Object storage, backups and observability

```text
S_docs  ≈ D_m × P_d × 0.5 MB × months_retained
S_audio ≈ H_a × 60 MB × (24 / 730)      # audio is deleted after 24 h
S_obj   ≈ S_docs + S_audio + exports + 30% headroom
S_backup ≈ (S_pg_total + S_obj) × backup_copies (1.5–2)
```

Example: 2,000 documents/month × 10 pages × 0.5 MB × 12 months = 120 GB before compression/dedup. Add versioning and backups. Audio is transient but its bucket and lifecycle still need capacity and monitoring.

```text
S_obs ≈ events/day × 1 KB × retention_days × replicas
```

For 30-day metrics and 30-day Langfuse metadata, plan 30 GB (laptop), 100 GB (demo), 500 GB (hosted pilot), 2 TB (production) as a starting point; measure actual cardinality. Do not enable content capture to "make traces useful."

### 3.5 Notifications and external model usage

```text
SMS_segments = N_sms × 1.5          # multilingual/concatenated messages
SMS_cost     = SMS_segments × SMS_unit_price
Email_cost   = N_email × email_unit_price
Slack_cost   = Slack_seats × Slack_seat_price
LLM_cost     = external_tokens × blended_price (input/output split)
```

Notification cost is small relative to model cost at demo scale, but SMS is the channel most likely to surprise at pilot scale. Budget per channel and monitor delivery failures, not just spend.

### 3.6 FinOps formulas (shared with the product)

```text
monthly_infra    = capex / amortisation_months + opex_monthly
cost_per_booking = (allocated_infra + model_cost + notification_cost) / bookings
cost_per_answer  = (allocated_infra + model_cost) / answered_questions
cost_per_user    = (monthly_infra + model_cost + notification_cost) / MAU
cost_per_1k_req  = (monthly_infra + model_cost + notification_cost) / (requests_month / 1000)
gross_margin     = (revenue − variable_cost) / revenue
break_even       = fixed_monthly_cost / contribution_per_booking
```

Every output carries `model_version`, `inputs_hash`, `as_of`, currency, FX rate/date, price-catalogue version and scenario name. The same functions are used by `scripts/export-finops.sh`, the analytics snapshot job and the what-if UI; a divergent formula is a defect (`ANL-AC-06`).

---

## 4. Reference profiles and bill of materials

All amounts are **indicative planning ranges in INR, excluding GST**, as of 2026-10-25. Ranges cover different vendors, warranty terms and build quality; they are not quotes. `—` means not applicable or included in another line.

### 4.1 Topology summary

| Profile | Demand | Topology | Availability | Local models |
|---|---|---|---|---|
| **P — Laptop pilot** | 100 req/h, 10 runs, 40k chunks, 10 audio h/month | Mac M4 Pro (14-core CPU, 20-core GPU), 26 GB unified, 1 TB; Compose `minimal`/`core`; `full` in bounded windows; host Ollama | Single host; no HA claim | 7–8B Q4 + 3–4B Q4 + `bge-m3` + STT small + PII + decider within ≈7 GB |
| **S — Demo/acceptance** | 500 req/h, 50 runs, 60k chunks | One 16 vCPU / 64 GB host, 2 TB NVMe; all Compose `core` services; optional 24 GB GPU | Single host; best-effort | Optional 24 GB GPU; external `main` for de-identified |
| **M — Hosted pilot** | 1,400 req/h, 100 runs, 500k chunks | 2 app nodes, 1 DB, Redis, MinIO/storage, 1 × 48 GB GPU, backup, firewall | N+1 app; DB backup/restore | 1 × 48 GB GPU for local W3/summary/insights |
| **L — Production HA** | 1,400 req/h with 4× burst, 250 runs, 2M chunks | 3 app nodes, DB primary+standby, Redis HA, 3 storage nodes, 2 × 48 GB GPU, observability, WAF/LB | Multi-AZ; RPO/RTO per architecture §11.6 | 2 × 48 GB GPU; external only de-identified |

**P is the current pilot host (`Q-28`, `D-19`).** It exists so the client can run the real stack on a laptop without pretending it is production. S is the reproducible acceptance host; M is the first hosted pilot; L is the production HA topology. Moving from P to M is a capacity decision, not a code change.

### 4.2 Capex BoM (laptop and on-prem/colo)

**P — laptop pilot.** The Mac is already owned; incremental capex is ₹0. If replaced for the pilot, a comparable machine is ₹2.2–3.2 lakh, plus ₹0.2–0.4 lakh for dock/display and ₹0.1–0.2 lakh for a UPS: **≈₹2.5–3.8 lakh replacement cost**, not an incremental project purchase. It has no HA, no ECC, no redundant storage and no independent backup; backups must go to an external encrypted target.

| Line item | S qty | S unit (₹ lakh) | S extended (₹ lakh) | M qty | M unit (₹ lakh) | M extended (₹ lakh) | L qty | L unit (₹ lakh) | L extended (₹ lakh) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Application/compute server (16c/64 GB or 8c/32 GB) | 1 | 3.0–4.5 | 3.0–4.5 | 2 | 2.2–3.0 | 4.4–6.0 | 3 | 3.0–4.0 | 9.0–12.0 |
| DB server (8c/64 GB or 16c/128 GB, NVMe) | — | — | — | 1 | 3.0–4.0 | 3.0–4.0 | 2 | 7.0–9.0 | 14.0–18.0 |
| Redis/cache server | — | — | — | 1 | 0.9–1.5 | 0.9–1.5 | 2 | 1.2–1.8 | 2.4–3.6 |
| Object storage server (8–12 TB) | — | — | — | 1 | 2.0–3.0 | 2.0–3.0 | 3 | 3.5–4.5 | 10.5–13.5 |
| GPU server (24 GB L4-class or 48 GB L40S/A6000-class) | 0–1 | 4.0–6.0 | 0–6.0 | 1 | 12.0–16.0 | 12.0–16.0 | 2 | 14.0–18.0 | 28.0–36.0 |
| Backup appliance/storage (2–20 TB) | 1 | 0.4–0.8 | 0.4–0.8 | 1 | 1.5–2.2 | 1.5–2.2 | 1 | 4.0–6.0 | 4.0–6.0 |
| Network: switch, firewall, load balancer | 1 | 0.8–1.5 | 0.8–1.5 | 1 | 2.0–3.0 | 2.0–3.0 | 1 | 6.0–10.0 | 6.0–10.0 |
| UPS/power distribution | 1 | 0.7–1.2 | 0.7–1.2 | 1 | 1.0–1.5 | 1.0–1.5 | 1 | 2.5–4.0 | 2.5–4.0 |
| Rack/colo setup/deposit | — | — | — | 1 | 0.5–1.5 | 0.5–1.5 | 1 | 1.5–3.0 | 1.5–3.0 |
| Installation, hardening, acceptance | 1 | 0.5–1.0 | 0.5–1.0 | 1 | 1.0–2.0 | 1.0–2.0 | 1 | 1.5–3.0 | 1.5–3.0 |
| **Subtotal** | | | **5.4–9.0 (no GPU) / 9.4–15.0 (with 24 GB GPU)** | | | **28.3–40.7** | | | **79.4–109.1** |
| Contingency 10% | | | 0.5–0.9 / 0.9–1.5 | | | 2.8–4.1 | | | 7.9–10.9 |
| **Indicative capex** | | | **≈6–10 (no GPU) / 10–17 (with 24 GB GPU)** | | | **≈31–45** | | | **≈87–120** |

**Notes:**

- P is not a purchase line; it is the owned pilot host. Do not add it to S/M/L TCO as if it were a server.
- The S profile is usually better on a cloud VM or an existing workstation than a dedicated purchase. Its capex is shown for a site that insists on a local demo box.
- M/L DB and storage lines assume local NVMe/HDD with RAID and a spare disk; they do not include a SAN. A SAN or shared storage adds cost and operational complexity.
- GPUs have the widest price and lead-time variance. If a 48 GB GPU is unavailable, 24 GB covers 8B Q4 but not a 70B model; do not promise local 70B without a measured quote.
- Developer laptops are not acceptance environments.

### 4.3 Opex BoM (monthly, laptop and on-prem/colo)

| Line item | Formula | P — Mac (₹/month) | S (₹/month) | M (₹/month) | L (₹/month) |
|---|---|---:|---:|---:|---:|
| Power | `kW × 730 × P_kwh × PUE` | 800–1,500 | 2,000–5,000 | 15,000–25,000 | 40,000–60,000 |
| Colo/rack/space | contract | 0 | 0–5,000 | 15,000–30,000 | 40,000–70,000 |
| Bandwidth/internet | contract | 0 (existing) | 3,000–6,000 | 6,000–12,000 | 15,000–25,000 |
| Offsite backup/object copy | storage × unit price | 500–1,500 | 2,000–4,000 | 5,000–10,000 | 12,000–20,000 |
| Hardware support/warranty | 8–12% capex/year | 0 (warranty) | 4,000–8,000 | 20,000–35,000 | 60,000–100,000 |
| External LLM API | tokens × price | 5,000–20,000 | 15,000–40,000 | 40,000–100,000 | 200,000–400,000 |
| SMS/email/Slack | per-unit | 500–2,000 | 2,000–6,000 | 8,000–18,000 | 25,000–50,000 |
| Operations/FinOps time | FTE × loaded cost | 0 (owner) | 0 | 15,000–25,000 | 40,000–60,000 |
| **Indicative opex** | | **≈6,300–25,000** | **≈30,000–70,000** | **≈1.3–2.2 lakh** | **≈4.5–7.5 lakh** |

The largest variable is external model spend, not electricity. Local models reduce token spend but add memory/power and model-ops time; the break-even depends on utilisation (see §7). The P row excludes the owner's time and assumes the laptop already exists.

### 4.4 Opex BoM (India cloud, monthly)

| Line item | P-equivalent small cloud VM (₹/month) | S (₹/month) | M (₹/month) | L (₹/month) |
|---|---:|---:|---:|---:|
| Application compute (VM/K8s) | 8,000–15,000 | 35,000–55,000 | 50,000–80,000 | 1.5–2.2 lakh |
| Managed Postgres/pgvector | 5,000–12,000 | 20,000–35,000 | 50,000–90,000 | 1.8–2.8 lakh |
| Redis/cache | 2,000–5,000 | 5,000–10,000 | 10,000–20,000 | 30,000–50,000 |
| Object storage + requests | 1,000–3,000 | 3,000–8,000 | 8,000–18,000 | 40,000–70,000 |
| GPU compute (24/48 GB) | 0 (local laptop) | 0–60,000 (on demand) | 100,000–160,000 | 4.0–6.0 lakh |
| Observability | 2,000–6,000 | 5,000–15,000 | 20,000–40,000 | 50,000–90,000 |
| Backup/snapshots | 1,000–3,000 | 2,000–5,000 | 8,000–15,000 | 25,000–50,000 |
| Egress/network | 1,000–4,000 | 2,000–8,000 | 10,000–25,000 | 30,000–70,000 |
| External LLM API | 5,000–20,000 | 15,000–40,000 | 40,000–100,000 | 200,000–400,000 |
| SMS/email/Slack | 500–2,000 | 2,000–6,000 | 8,000–18,000 | 25,000–50,000 |
| Support/ops | 0–5,000 | 0–10,000 | 15,000–30,000 | 40,000–80,000 |
| **Indicative opex** | **≈26,000–75,000** | **≈90,000–1.5 lakh (GPU on demand: +50,000)** | **≈3.2–4.6 lakh** | **≈12–17 lakh** |

The P-equivalent cloud column is what it would cost to host the laptop pilot's workload in one India-region VM with managed Postgres and object storage; it is not the pilot's actual cost. Cloud prices vary by region, commitment and GPU availability. Reserved/committed use can reduce steady-state compute by 20–40%; on-demand GPU for demo/eval is cheaper than 24/7. Do not compare an on-demand cloud total with a 3-year reserved total.

### 4.5 Three-year total cost of ownership (planning)

```text
TCO_3y = capex + (opex_monthly × 36)
```

| Profile | On-prem/colo (₹ lakh) | India cloud (₹ lakh) | Comment |
|---|---:|---:|---|
| **P — laptop pilot** | **0 capex + 2.3–9.0 opex ≈ 2.3–9.0** (replacement: 4.8–12.8) | **≈9.4–27.0** | Owned hardware; power/backups/model spend only; no HA |
| S — demo/acceptance | 6–17 capex + 11–25 opex ≈ **17–42** | **32–54** | A laptop/existing host is cheaper; cloud is simpler to reproduce |
| M — hosted pilot | 31–45 capex + 47–79 opex ≈ **78–124** | **115–166** | On-prem wins on 3-year TCO if the site has power/rack and ops capacity |
| L — production HA | 87–120 capex + 162–270 opex ≈ **249–390** | **432–612** | Cloud premium buys elasticity, managed HA and reach; on-prem requires a real DR site |

These totals exclude implementation services, integration, security assessment, SMS/email/LLM overage and the client's own staff. Recompute with quotes; do not present a range midpoint as a budget without the client's approval.

---

## 5. Worked sizing examples

### 5.1 Demo/acceptance (S)

- `R=500`, `b=4` → `rps_burst=0.56`; 2 vCPU API minimum is sufficient; use a 16 vCPU host for Compose density and headroom.
- `K=60,000`, 1,024-d vectors → HNSW/index ~0.3 GB; 8–16 GB DB RAM is enough for the demo.
- `D_m=500`, `P_d=10`, 12 months → ~30 GB documents; audio 20 h/month × 24/730 → negligible; 2 TB NVMe covers data + backups.
- `C=50` → SSE/Redis and API memory, not CPU, dominate. 1 GB Redis is enough for queues; 2 GB is safer.
- External model: 1,500 turns/day × 2.5k tokens ≈ 3.75M tokens/day worst case; at planning prices this is a real monthly cost. Use the deterministic/stub route for load tests and cap the real-model run.
- GPU: optional; W3 demo can use a 24 GB GPU or a transcript-upload fallback. Do not buy a GPU only for the demo unless local W3 is a must.

### 5.2 Hosted pilot (M)

- `R=1,400`, `b=4` → `rps_burst=1.56`; 2 app nodes at 8 vCPU / 32 GB provide N+1 and room for SSE/graph work.
- `K=500,000` → HNSW ~2.7 GB; DB 8 vCPU / 64 GB with NVMe and 30% working space.
- Documents: 2,000/month × 10 pages × 0.5 MB × 12 ≈ 120 GB; add versions/backups → 8 TB storage is comfortable for year 1.
- Audio: 200 h/month, 24-hour retention → a small transient bucket; STT concurrency is the constraint, not storage.
- GPU: one 48 GB card serves local 8B W3/summary/insights with queues; if `C_local` exceeds measured concurrency, route de-identified text externally or hand off.
- Opex: external model spend often dominates. Instrument cost per booking/answer before assuming the GPU pays for itself.

### 5.3 Laptop pilot (Mac M4 Pro 26 GB)

The Mac runs the same Compose stack with caps. Planning budget:

| Component | Budget (GB) | Notes |
|---|---:|---|
| macOS + background | 5.0 | Leave the OS room; do not max the Docker VM |
| Docker VM services | 12.8 | Postgres 2.2, Redis 0.3, MinIO 0.4, Keycloak 1.0, LiteLLM 0.6, MCP 1.2, API 1.2, worker 1.2, scheduler 0.2, Langfuse 2.0, OTel 0.3, web 0.1, PII 1.2, STT 0.9 |
| Host Ollama | 6.5 | 7–8B Q4 + KV + `bge-m3`; one model loaded at a time |
| **Total** | **24.3** | **≈1.7 GB headroom; measured and capped at G1** |
| Not concurrent | — | Prometheus, Grafana, ClamAV and the load generator; run `full` in a bounded window with Ollama stopped |

- Docker Desktop memory: ≈14 GB; host Ollama ≈7 GB; if swap appears, stop Langfuse or STT, use `core`, and reduce local model concurrency. Do not raise memory beyond what macOS can spare.
- `K=40,000`, 1,024-d vectors → <0.2 GB index; Postgres 2.2 GB is enough with capped buffers.
- External model share `E=40%`; local routes cover W3/summary/titles/embeddings. At 1,000 turns/day, external spend is a few thousand rupees per month at planning prices, not a token for a 50k-user production load.
- Audio 10 h/month with 24-hour retention is transient; STT `small` int8 is CPU/Metal-bound.
- **What P cannot prove:** 1,400 req/h with 4× burst, N+1 failover, multi-AZ, 250 concurrent runs, 2M chunks, or production HA. Use M/L for those claims.

### 5.4 Production HA (L)

- `R=1,400`, `b=4` → `rps_burst=1.56`; 3 app nodes for AZ spread and rolling upgrades; HPA on latency/queue, not CPU alone.
- `K=2,000,000` → HNSW ~10.6 GB; DB 16 vCPU / 128 GB with a read replica for analytics/retrieval; partition audit/usage/events by month.
- Storage: 120,000 docs/year × 5 MB ≈ 600 GB; 1,000 audio hours/month with 24-hour retention; 12 TB across three nodes plus offsite backup.
- GPU: two 48 GB cards for local-only paths and headroom; external de-identified traffic remains subject to the egress gate.
- HA: multi-AZ DB, Redis, object storage and GPU pool; load balancer/WAF; DR site or cross-region backup per the client's RPO/RTO. This is where cost rises non-linearly.

---

## 6. Hosting model decision and what-if scenarios

| Criterion | On-prem (hospital) | Colo | India cloud | Hybrid |
|---|---|---|---|---|
| Data residency | Strongest control; site-dependent | Strong control; provider is a subprocessor | Region-pinned; verify subprocessors | Local data plane, cloud control plane |
| Capex vs opex | High capex, lower run rate | Medium capex, medium run rate | Low capex, higher run rate | Split |
| GPU availability | Procurement lead time; fixed | Procurement lead time; fixed | Elastic but scarce/expensive; quota needed | GPU local, burst cloud |
| HA/DR | Requires a second site; hard | Second site or provider DR option | Managed multi-AZ, easier | Depends on design |
| Operations | Hospital IT owns hardware/patches | Provider owns facilities; app team owns stack | Provider owns hardware; app team owns config | Shared responsibility, clear boundary |
| Latency | LAN; good for front desk | LAN/WAN; measure | Internet/VPN; measure | Local for clinical, cloud for analytics |
| Exit | Hardware resale; low lock-in | Contract/egress terms | Egress/data-export cost; API-specific services | Moderate |
| Best fit | Client mandates on-prem and has a rack/ops team | Hospital wants control without owning facilities | Fast pilot/production with HA and elasticity | Hospital wants local PHI and cloud analytics |

**Default recommendation (`Q-25`, answered):** pilot on the existing Mac M4 Pro, then a hosted pilot on-prem/colo **if** the hospital provides power, rack, backup and an ops owner; otherwise India cloud; production on a managed India cloud with reserved compute unless DPDP/security policy requires on-prem. Record the choice as an ADR and re-run this model.

### 6.1 Scenario definition for the what-if UI

Each scenario is a named set of inputs, not a different formula:

| Scenario | Hosting | Capex treatment | Opex treatment | GPU |
|---|---|---|---|---|
| `laptop_pilot` | Owned Mac | ₹0 incremental; replacement optional | Power + backup + model/notification spend | Unified memory, small models |
| `colo` | Client rack | Full capex BoM | Power/colo/bandwidth/support + model | Purchased GPU |
| `on_prem` | Hospital data centre | Full capex BoM + internal chargeback | Power/space/support + model | Purchased GPU |
| `india_cloud` | Managed India region | ≈0 | Subscription/reserved compute + storage + egress + model | On-demand/reserved GPU |
| `hybrid` | Local data/models + cloud burst/analytics | Partial capex | Split subscriptions + model | Local GPU + cloud burst |

### 6.2 What-if outputs

For every scenario the UI and `scripts/export-finops.sh` must show:

- capex, monthly opex and 3-year TCO with a range;
- cost per booking, answer, signed note, active user and 1,000 requests;
- gross margin and break-even at the configured price book;
- sensitivity to utilisation, FX, power tariff, GPU price, external-model share and retention;
- the assumptions and `model_version`/`inputs_hash`, labelled **estimate**.

AI recommendations are advisory: they cite the scenario, the changed inputs, the delta and the evidence. They cannot change a budget, price, route or configuration without an audited human action (`D-12`, `D-26`).

### 6.3 Growth model

Growth is stepwise because capacity arrives in steps. This table is an example for the product's FinOps dashboard, not a forecast:

| Year | Registered / MAU | Chunks | Audio h/month | Profile at year-end | Indicative incremental capex (₹ lakh) | On-prem opex (₹ lakh/month) | Cloud opex (₹ lakh/month) |
|---|---:|---:|---:|---|---:|---:|---:|
| 1 | 10,000 / 3,000 | 500,000 | 200 | M | 31–45 | 1.3–2.2 | 3.2–4.6 |
| 2 | 25,000 / 8,000 | 1,200,000 | 500 | M+ (add app/storage/GPU headroom) | 15–25 | 2.1–3.4 | 5.0–7.0 |
| 3 | 50,000 / 20,000 | 2,000,000 | 1,000 | L | 40–70 (reuse M capacity) | 4.5–7.5 | 12–17 |

The curve is driven by the §2 inputs, not by headcount alone. Increasing MAU without increasing turns, documents or audio barely moves infrastructure; increasing concurrency, local-model share or retention moves it quickly. The FinOps dashboard must plot both capex and opex against users/volumes and state the step that caused the change (`Q-27`).

---

## 7. FinOps, unit economics and profitability

Infrastructure cost is one input to unit economics, not a separate truth.

- **Attribution:** direct clinic/workflow usage comes from `usage_record`; shared platform cost (DB, gateway, observability) is allocated by a documented rule (active users or requests), not guesswork. Showback uses the same rule as the FinOps tab. Chargeback is post-handover (`roadmap.md`).
- **Amortisation:** use the client's finance policy (typically 36 months for servers, 24–36 for GPUs). State the period on the report.
- **Currency:** infra costs are in INR; model costs are USD with an INR conversion rate and date. Do not mix them without a visible rate.
- **Price book:** budgets, prices, profitability and allocation are configurable; no production price is assumed in code.
- **Local vs external break-even:** `external_token_cost_per_month` versus `GPU_amortised + power + ops + utilisation loss`. At low utilisation, external is usually cheaper; at sustained high utilisation, local can win. Measure with LiteLLM/local usage, not intuition.
- **Savings levers:** reserved/committed cloud, right-sizing after four weeks, scheduling non-prod off, object lifecycle, embedding batching, purpose routing, prompt/context reduction, caching deterministic artefacts, and using deterministic/stub routes for load. Each accepted lever goes into the FinOps savings register (`FR-FIN-07`).
- **Profitability:** `contribution_per_booking`, `gross_margin` and `break_even` use the configured price book and the same allocated cost. A scenario that improves margin by weakening safety is rejected.
- **Privacy:** cost rows and showback exports are aggregate by clinic/workflow/model/period. No patient-level data; small-cell suppression applies.

---

## 8. Right-sizing and review process

| Trigger | Action |
|---|---|
| API CPU > 70% for 15 min at peak, or p95 breach for 3 consecutive windows | Add a replica or raise the node size; check DB/LLM first |
| API memory > 80%, OOM/restart | Raise memory, reduce per-run context, inspect SSE/run leaks |
| Mac memory pressure/swap during `core` | Stop optional services (Langfuse/STT), reduce local concurrency, move Ollama off-host or use external de-identified; record the variance |
| DB CPU > 70%, connections > 80%, slow queries | Add a read replica, tune indexes/queries, partition; do not just add RAM |
| HNSW recall/latency degrades | Tune `ef_search`/`m`, add memory, or re-index; measure recall |
| GPU queue wait > 2× target or memory > 85% | Add a GPU, cap local concurrency, or route de-identified traffic externally |
| Object storage > 70% or lifecycle lag | Expand, verify retention/deletion, check orphan scan |
| Analytics snapshot > schedule | Scale the analytics worker, optimise the query, or reduce refresh scope |
| Cost per booking/answer > target | Route to a cheaper model, reduce tokens, cache, renegotiate; never lower safety |
| Utilisation < 40% for 4 weeks | Downsize or consolidate; keep HA requirements |
| Load target rises above the current profile | Re-run §2–§3; move P → M or M → L; do not claim the new target on old hardware |

Review cadence: weekly during delivery, monthly in a pilot, quarterly in production. Every change records before/after p95, error rate, cost per outcome and the load-test profile. The model is re-run at G0, G1, G5 and G6; results feed [plan.md](./plan.md), the FinOps dashboard and `config/finops_model.yaml`.

---

## 9. Security, residency and compliance constraints

- All production data stores, backups and model services run in India/in-boundary. External model calls carry only de-identified text (`NFR-PRIV-01`); Slack/SMS/email carry no clinical detail; staff and patient Slack workspaces are separate.
- Encryption at rest and in transit; separate DB roles; private object buckets; no public data ports; secrets from a manager, not images.
- Backups are encrypted, access-controlled and restore-tested; audit anchors use object lock where available.
- Network zones follow architecture §3.3; egress allowlists cover OpenRouter, SMTP, SMS and Slack. FHIR is a reserved future egress destination; no FHIR adapter or endpoint is called in this build (G-08).
- FHIR is a target read-only integration, not delivered; ABDM linking/certification is also not delivered. A real HIS integration requires the adapter, client credentials, a security review and a data-processing agreement.
- Vendor/subprocessor review is required before production; the hosting ADR records region, provider, data classification and exit plan.
- A hardware BoM does not make the system compliant. DPDP notice, consent, retention and breach processes remain product/legal work.
- The Mac pilot holds only synthetic/public data and the approved test workspaces; it is never the production data plane.

---

## 10. Assumptions and exclusions

- Prices are indicative Indian market ranges for planning; they exclude GST, freight, installation labour variations, extended warranties and currency hedging.
- The model assumes open-source software (Postgres, Redis, MinIO, Keycloak, LiteLLM, Langfuse, OpenTelemetry) with no licence fee. Enterprise support, if required, is additional.
- It excludes implementation/consulting, HIS/ABDM certification, security certification, penetration testing, training and the client's staff time.
- It excludes LLM/STT/OCR provider price changes and promotions; use the price catalogue effective date.
- It excludes a second DR site for the on-prem L profile; add 60–100% of the production infrastructure for a true active/passive DR site.
- It assumes synthetic/public data for the demonstration and pilot. Real patient data requires a production DPDP review, not just this BoM.
- Cloud totals assume a single India region; multi-region active-active is out of scope ([architecture.md §16.3](./architecture.md#163-deferred-items-and-revisit-triggers)).
- The laptop pilot assumes the Mac is already owned and is not repurposed for production; replacement cost is shown separately.
- The growth table is an illustrative planning curve, not a commitment or a forecast of demand.

---

## 11. Decisions recorded (formerly open questions)

All sizing and hosting questions are answered in [spec.md](./spec.md#10-open-questions). The model applies them as follows:

| ID | Answer applied | Effect on this document |
|---|---|---|
| Q-25 | Pilot on the existing laptop; hosted/on-prem/cloud depends on the hospital's rack and policy; production India cloud unless mandated otherwise | P is the current pilot; M/L remain options; §6 keeps the trade-off visible |
| Q-26 | No capex ceiling assumed; budgets configurable; recommendations from observed usage | Ranges and the savings register; no fixed budget claim |
| Q-27 | Demo 500 req/h; pilot 1,400 req/h with 4× burst; production same with HA; growth shown as users grow | Inputs, growth table and FinOps growth chart |
| Q-28 | Pilot on the product owner's Mac M4 Pro 26 GB; a better host when hosted | P profile, §5.3 memory budget, P→M step |
| Q-29 | Trade-off across colo, cloud and on-prem; UI what-if; AI recommendations | §6 scenarios and §6.2 outputs |
| Q-30 | RPO 24 h baseline/15 min target; RTO 4 h; single-site pilot | P/S single-site; L multi-AZ/DR note |
| Q-31 | Staff and patient/other-user Slack test workspaces | Notification cost lines and separation in [setup.md](./setup.md#75-slack-identity-and-patient-opt-in) |
| Q-32 | Real adapters; credentials in `.env`/vault; no runtime mocks | Opex per-channel lines; `unconfigured` state adds no simulated cost |

There are no open sizing questions. A future change to volumes, hosting, FX, tariffs or the price book is a model input change with a new `model_version` and an audit record, not an open question.

---

## 12. Sources and verification

Checked on **2026-10-25** for this document:

- Architecture sizing and profiles: [architecture.md](./architecture.md) §3, §6.7, §11, §14.
- FinOps requirements and formulas: [spec.md](./spec.md) §5.17; [architecture.md](./architecture.md) §10.7.
- Retention and data classification: [spec.md](./spec.md) §6.5; [architecture.md](./architecture.md) §6.9.
- Deployment profiles and ports: [architecture.md](./architecture.md) §14; [setup.md](./setup.md) §2–§3.
- Decisions: [spec.md](./spec.md) §11 (`D-01`–`D-28`, Q-25–Q-32).
- Public price references are intentionally not hard-coded as vendor quotes; use current India-region price pages, GPU quotes and the client's tariff/FX at procurement. The numbers in §4 are planning ranges, not claims about a specific vendor.

If a source conflicts with this document, the order is: requirements → architecture → this sizing guide → plan. Update the model and record the decision; do not silently change a number in a slide.
