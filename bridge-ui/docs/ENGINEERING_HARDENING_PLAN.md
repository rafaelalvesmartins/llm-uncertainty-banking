# Bridge — Enterprise Architecture & Infrastructure Hardening Plan

> **Status:** proposal · **Authored:** 2026-06-14 · **Branch:** `product/bridge-platform` · **Reconciled against HEAD `e22242f`**
>
> **⚠️ Reconciliation note (verified against the code at HEAD):** the audit's three top defects were **already fixed in commit `e22242f`** ("scope semantic cache per-customer + at-rest audit verification"), landed right after the audit: **R1** (cache now scoped — `memory.py:179 if entry.scope != scope`, `test_cache_confidentiality.py` regression test), **R2** (`GET /audit/verify?source=disk` re-validates the full persisted chain — `routers/audit.py:118`), **R3** (import-time proxy assertion — `server.py:2001-2006`). Only **R4 remains partially open** (queue depth now locked via `_OLLAMA_QUEUE_LOCK`; the breaker read-modify-write is still unlocked, and bridge-ui still has no CI). The plan below is updated accordingly — the remaining work is **enforcement, not firefighting.**
> **Scope:** the `bridge-ui` demo platform (FastAPI backend + Next.js frontend), with parity targets borrowed from the `lub` library's existing engineering bar.
>
> **This is a north-star document.** It does not replace the existing plans — it *sequences and unifies* them into one program with enforceable guardrails:
> - `ARCHITECTURE_REVIEW.md` — the 2026-06-14 multi-agent audit (the verified defects R1–R4).
> - `../backend/DECOUPLING_PLAN.md` — the completed server.py → 7-module extraction.
> - `PRODUCT_PLAN_V6.md` — the trust-substrate production phases (auth → tenancy → KMS).
> - `DEMO_SCOPE.md` — what is intentionally out of scope (do not re-litigate).
>
> **Guiding honesty principle (inherited from the team):** never fake a control; mark demo-grade clearly; every change is additive and reversible; the demo path (`BRIDGE_AUTH=off`) keeps working at every step.

---

## 0. TL;DR — the one-paragraph thesis

The decoupling already done is genuinely good (acyclic `server → backends → core.responses`; a re-export shim for pure units and a module-attribute proxy for stateful ones), and the team fixes defects fast — the audit's three worst findings (R1/R2/R3) were closed by hand within one commit of the report. **That speed is exactly the problem this plan addresses:** the fixes are real but **unenforced** — there is no CI, no type-gate, and no import-linter contract on `bridge-ui` (unlike `lub`), so nothing stops the next PR from silently re-coupling the modules or regressing the cache-scope fix. The highest-leverage enterprise move is therefore not more firefighting — it is to **make the architecture and the safety properties executable as fitness functions** (import-linter + mypy + a CI gate that runs the existing `test_cache_confidentiality.py` and safety-smoke suites on every PR), then close the one residual defect (R4's breaker lock + tests), and only then walk the documented production phases. In short: **the team is good at fixing; encode the invariants so they don't rely on heroics.**

---

## 1. Where we are (ground truth)

**Two artifacts, two maturity levels:**

| Component | What it is | Engineering bar today |
|---|---|---|
| `lub/` (library) | The real calibration/governance framework | **Enterprise:** import-linter layered contract, `mypy --strict`, ruff, `bandit -ll`, `pip-audit --strict`, 80% coverage gate, hermetic e2e, wheel build, py3.11/3.12 matrix |
| `bridge-ui/backend` | FastAPI demo wrapping `lub` | server.py 2,010-line composition root + 7 extracted modules; 21 routers; 23 test files; **no pyproject, no mypy, no import-linter, no CI** — a local safety git-hook only |
| `bridge-ui/frontend` | Next.js 14 dashboard | App Router, plain CSS, 30 components, BFF proxy, `featureMap` honesty layer; `dev/build/lint/e2e` scripts, **no CI** |
| `reference/` | Documented prod integration | `docker-compose`: gateway + **Postgres** + Prometheus + Grafana, env-driven — the productionization target already sketched |

**The asymmetry is the headline:** `lub` is held to a contract; `bridge-ui` is held to good intentions. Every recommendation below either closes that gap or fixes a defect the audit confirmed against running code.

**Decoupling status (from `DECOUPLING_PLAN.md`):** `core/{guard,classifier,responses}`, `backends`, `models`, `state/{audit,runtime}` extracted; `pipeline` deliberately left in `server.py` as the composition root (correct — extracting it would only relocate coupling and add `s.` indirection).

---

## 2. Enterprise principles this plan is built on

1. **Architecture as fitness functions.** A structural rule that isn't machine-checked is already decaying. Decoupling must be expressed as an import-linter contract, not a wiki page.
2. **Blast-radius isolation.** Per-tenant/per-customer state must be isolated by construction; a global singleton holding cross-customer data is a coupling defect, not just a scaling concern (see R1).
3. **Defense in depth + segregation of duties.** Controls (guard, DQ, PII, SoD) layer; identity is *verified*, never trusted-from-body.
4. **Supply-chain integrity.** Pinned deps, SBOM, dependency + static scans in CI (lub already does this; bridge-ui doesn't).
5. **Additive & reversible.** Every step ships behind a flag or as a new seam; the demo never breaks.
6. **SLOs over vibes.** Latency/availability/queue-depth are measured against explicit targets, surfaced in Prometheus/Grafana.

---

## 3. Track A — Code decoupling & correctness ("desacoplar", enforced)

### A1 — Promote the decoupling to an architectural fitness function ⭐ *highest leverage*

Today `server → backends → core.responses` is acyclic *by discipline*. Make it a **contract**, mirroring `lub`'s `[tool.importlinter]`:

- Add `bridge-ui/backend/pyproject.toml` with an `import-linter` contract:
  - **Layers:** `core` (pure) < `models` < `state` < `backends` < `server` (composition root). Lower layers must not import higher ones.
  - **Forbidden:** `core/*` and `backends.py` must **not** `import server` (this is exactly the circular hazard the responses-leaf extraction solved — now *enforced*, so it can't regress).
  - **Independence:** `core/guard`, `core/classifier`, `core/responses` import nothing from each other.
- Wire `lint-imports` into the new bridge-ui CI job (Track B).
- **Verify:** deliberately add `import server` to `core/guard.py` → CI fails. *(Effort: S. This single contract is what makes all prior decoupling permanent.)*

### A2 — The two correctness defects (audit R1, R2) — ✅ **already fixed in `e22242f`**

Both are closed at HEAD; the only remaining action is to **stop them regressing** (which is Track B / B1):

- **R1 — semantic-cache cross-customer leak — CLOSED.** `SemanticCache.lookup(query, *, scope)` now filters by scope (`memory.py:179`), and the pipeline passes `scope=req.customer_id` (`server.py:1096`, store at `:1306`). A regression test exists (`test_cache_confidentiality.py`). **Residual:** ensure that test runs in the bridge-ui CI gate (B1) so the isolation can't silently regress. This is also the seam Phase-3 tenancy reuses — swap `customer_id` for `tenant_id`.
- **R2 — audit chain verifiable at rest — CLOSED.** `GET /audit/verify?source=disk` (`routers/audit.py:118`) re-runs `_audit_chain_break()` over the full persisted SQLite chain (`state/audit.py:84`); `source=memory` remains the fast window check. **Residual:** add a test that an out-of-band `UPDATE audit_entries` is caught by `?source=disk` (lock it in CI).

### A3 — Proxy seam hardening (audit R3) — ✅ **mostly done**

The import-time assertion already exists: `server.py:2001-2006` loops `_PROXIED_ATTRS` and raises at import if any proxied name isn't defined on its owner module — so an unregistered scalar fails at import, not at first read. **Residual (optional, S):** a pre-commit grep for *bare* proxied-name references inside `server.py`'s own functions (the documented `__getattr__` gotcha — bare-name reads bypass the proxy). Cheap belt-and-suspenders.

### A4 — Optional, bounded: a `pipeline/components` seam

Do **not** extract the `/query` orchestration (the audit and decoupling plan both rate this correctly as "leave in composition root"). But the ~8 pipeline-component singletons still inline in `server.py` (`_DQ_*`, `_GOVERNOR`, `_RAG`, `_CACHE`, `_RATE_LIMITER`, `_CUSTOMER_MEMORY`) can be grouped into a `components.py` constructed-and-injected bundle, so `server.py` wires a `Components` object rather than ~8 globals. This reduces the proxy surface and makes the cache-scope (A2/R1) change local. **Only do this after A1–A3**; it is a clarity win, not a correctness one — keep it surgical or skip it. *(Effort: M. Candidate, not mandatory.)*

### A5 — Frontend decoupling (use the `/console` shell as the model)

The legacy `app/page.tsx` is a 408-line client component importing all 30 panels; `globals.css` hardcodes hex tokens. The new `/console` redesign already demonstrates the target pattern: a **shared contract** (`components/console/{types,api}.ts`), a **shell** (rail + topbar), **route-scoped views**, and a **scoped design-token layer** (`.bridge-console` CSS vars). Generalize that:

- Extract a typed **BFF client layer** (`lib/api/*`) so components stop hand-rolling `fetch("/api/...")` (the audit's polling-burst finding lives here).
- Lift status/spacing/color into **CSS custom properties** (the `bc-*` token set is the prototype) instead of inlined hex.
- Adopt **route segments** (like `/console`) over the single hash-tab monolith for code-splitting.
*(Effort: M, incremental; the `/console` work is step 1 already done.)*

---

## 4. Track B — Test & CI/CD parity (make `bridge-ui` as rigorous as `lub`)

### B1 — Stand up a `bridge-ui` CI pipeline ⭐ (audit R4c) — *protects everything else*

`bridge-ui` has **no** GitHub Actions. Add `.github/workflows/bridge-ui.yml` running on every PR touching `bridge-ui/**`:

1. Backend: `ruff` · `mypy` · `lint-imports` (the A1 contract) · `pytest` with a coverage gate · the safety-smoke suite (currently only a local hook).
2. Frontend: `next lint` · `tsc --noEmit` · `next build` · `playwright test`.
3. Static/supply-chain: `bandit -ll` · `pip-audit` (mirror lub's gates).

**Verify:** a deliberate 6-spot-sync break, or `import server` in `core/`, fails CI. *(Effort: M — the single most valuable infra investment; without it every fix below can silently regress.)*

### B2 — Cover the real-LLM & concurrency paths (audit R4) — *partially done, the one open defect*

Progress since the audit: queue-depth mutation is now serialized under `_OLLAMA_QUEUE_LOCK` (`backends.py:123,131,139,145`) and the work runs under `_OLLAMA_SEMAPHORE`. **Still open:**

- The circuit-breaker read-modify-write `_ollama_record_failure` (`backends.py:102-112`) mutates `_OLLAMA_BREAKER_OPEN_UNTIL` + `_OLLAMA_FAILURES` **without a lock** — a real (if low-probability) race. **Fix:** wrap it in a breaker lock. *(S)*
- `OllamaBackend` breaker/queue/timeout has **no** unit coverage. **Fix:** opt-in real-Ollama tests (env-gated, skipped in CI) + a 10–50-thread `/query` load test asserting queue depth ≤ max and **monotonic audit seq** + chain-verifies-post-run. *(M)*

### B3 — Supply-chain & secrets hygiene

Pin/freeze backend deps (`requirements.txt` currently uses floors like `fastapi>=0.110`); generate an SBOM in CI; move demo credentials/personas to `.env.example` + a pre-commit secret scan (audit's cheap-win list). *(Effort: S.)*

---

## 5. Track C — Infrastructure & platform (turn `reference/` into a real path)

The team already documents the target (`reference/docker-compose.yml`: gateway + Postgres + Prometheus + Grafana). Sequence it as a real, gated program — this is the body of `PRODUCT_PLAN_V6`, restated as infra deliverables:

| Phase | Deliverable | Trigger / guardrail |
|---|---|---|
| **C0** | Containerize `bridge-ui` (gateway image), runtime secret injection, env-config audit (tighten CORS, security headers) | none — do alongside Track B |
| **C1** | Auth: `POST /auth/token` (EdDSA JWT) + `verify_token`, gated by `BRIDGE_AUTH=off` default; governance identity from `token.sub` | additive; demo path unchanged |
| **C2** | RBAC + audit attribution (role claims; SoD = approver `sub` ≠ submitter `sub`) | after C1 |
| **C3** | **Multi-tenant isolation** — `tenant_id` via `ContextVar`, columns on `audit_entries`/`change_requests` + `WHERE tenant_id=?` everywhere; tenant in signed evidence | ⚠️ **must ship before auth is mandatory** (else the R1-class leak goes multi-tenant) |
| **C4** | Data durability: SQLite **WAL now** (near-free); Postgres + PITR **only on real HA/concurrency need** (hash-chain is storage-agnostic) | trigger on concurrency/HA, not prematurely |
| **C5** | Observability: structured logs + correlation IDs; Prometheus metrics + Grafana SLO dashboard (per `reference/monitoring`) | after C0 |
| **C6** | Managed signing key + RFC 3161 TSA via a `KeyManager` seam | **blocked on the bank's KMS** — build the seam now, wire later; never fake |

**Ordering guardrail (non-negotiable):** Phase auth (C1) must **not** become mandatory before tenancy (C3) lands, or you convert "single-tenant demo" into "multi-tenant leak." This sequencing *is* the mitigation.

---

## 6. The unified program — Now / Next / Later

| When | Items | Effort | Why now |
|---|---|---|---|
| **Now (this week, days)** | **B1 (bridge-ui CI)** ⭐, **A1 (import-linter contract)** ⭐, B2 breaker lock + cache/disk regression tests wired into CI, mypy gate, B3 (WAL + secrets) | ~1 week total | R1/R2/R3 are already fixed — this makes those fixes **permanent** and self-enforcing. The shift from firefighting to guardrails. |
| **Next (weeks)** | B2 (LLM/concurrency tests + locks), C0 (containerize + config hardening), A5 (frontend BFF/token layer), C5 (structured logs + SLO dashboard) | 2–4 weeks | Hardening + ops visibility; unblocks a pilot conversation. |
| **Later (quarters, gated)** | C1→C2→C3 trust substrate, C4 Postgres (on need), C6 KMS/TSA (on bank KMS) | per `PRODUCT_PLAN_V6` | The legitimately deferred road to a paying pilot; each gated, none rushed. |

---

## 7. Guardrails that keep it decoupled (the enforcement layer)

- **import-linter contract** (A1) — structural decoupling can't regress silently.
- **`mypy --strict` on `bridge-ui/backend`** — parity with lub; catches the cross-module coupling that types reveal.
- **CI on every PR** (B1) — the safety-smoke 6-spot-sync rule, e2e, and the contracts run before merge, not just in a local hook.
- **Coverage gate** on the units (start at a realistic floor, ratchet toward lub's 80%).
- **Cross-tenant regression test** (from A2/R1) — a permanent assertion that isolation holds.

---

## 8. What NOT to do (anti-scope — matches the team's discipline)

- **Don't extract `pipeline.py`.** It's the composition root; extraction relocates coupling and adds indirection. (Audit + decoupling plan agree.)
- **Don't migrate to Postgres for the demo.** SQLite-WAL meets BCB retention; the hash-chain is storage-agnostic. Trigger on HA/concurrency only.
- **Don't fake KMS/HSM or multi-provider failover.** Build the seam; wire when the bank provides the substrate. Label evidence exactly as the code earns (process-verifiable, not externally time-bound).
- **Don't force `BRIDGE_AUTH` on early** — it bricks the dashboard and the prospect demo at once; flip only after C3 + a role-aware UI.
- **Don't re-litigate documented demo gaps** (FakeBackend, single language, placeholder PIX) as defects — they're in `DEMO_SCOPE.md` on purpose.

---

### Appendix — defect → fix → verify quick reference

| ID | Defect (file) | Sev | Status @ `e22242f` | Remaining |
|---|---|---|---|---|
| R1 | Semantic cache cross-customer leak (`memory.py:179`, `server.py:1096`) | HIGH | ✅ **Fixed** — scoped lookup + `test_cache_confidentiality.py` | Run that test in CI (B1) |
| R2 | Audit chain verified only at boot | HIGH | ✅ **Fixed** — `/audit/verify?source=disk` (`routers/audit.py:118`) re-validates persisted chain | Add out-of-band tamper test in CI |
| R3 | Manual proxy registration drift | MED | ✅ **Fixed** — import assertion `server.py:2001-2006` | Optional pre-commit bare-name grep |
| R4a | Ollama breaker RMW unlocked (`backends.py:102-112`) | HIGH | ⚠️ **Open** — queue locked, breaker not | Lock the breaker RMW |
| R4b | `/query` queue-depth check (`server.py:965`) | HIGH | ◐ Queue now under `_OLLAMA_QUEUE_LOCK` | Load test to confirm depth ≤ max |
| R4c | No `bridge-ui` CI | HIGH | ⚠️ **Open** | GitHub Actions: pytest+playwright+mypy+ruff+import-linter+bandit+pip-audit |

---

## 9. Track D — Scale architecture (millions of requests/day, low latency)

> **Beyond the v6 pilot.** v6 targets one paying bank on a single node; this is what it takes to serve millions of requests/day at low, predictable latency. Honestly a **refactor program**, summarized as: *make the app stateless, externalize state, scale the LLM tier.* Today the app is a single uvicorn worker with in-process state and a one-at-a-time LLM semaphore — fine for a demo, a hard ceiling for volume.

### D.0 — Capacity math (concrete targets)

| Daily volume | Avg req/s | ~Peak (4×) |
|---|---:|---:|
| 1M/day | ~12 | ~50 |
| 10M/day | ~116 | ~460 |

Modest in absolute terms — a well-built stateless service does this on a few cores; the current one can't, for the reasons below. The cheap stages (regex DQ, TF-IDF RAG, dict intent) are sub-ms; **cost is dominated by the LLM stage and the per-request durable audit write.** Optimize those, not the cheap stages.

### D.1 — Make the app stateless (the hard prerequisite)

Every in-process global moves to an external store so any replica serves any request:

| Today (in-process) | Target | Why |
|---|---|---|
| `_AUDIT` deque + SQLite hash-chain under `_AUDIT_LOCK` | **Postgres** append-only; **per-tenant** chain (not one global lock) or ordered async writer | the global lock is the serialization bottleneck |
| `_CACHE` (semantic) | **Redis** (keyed tenant+normalized query — R1 already scoped) | shared across replicas |
| `_RATE_LIMITER` | **Redis** token bucket per (tenant, customer) | |
| idempotency cache | **Redis** + TTL | |
| `_METRICS` counters | **Prometheus** (expose `/metrics`, scrape) | don't hold counts in-process |
| customer memory · `_RUNTIME_*` settings | Postgres / Redis, read-through cached | |

Result: replicas hold **no authoritative state** → horizontal scale + HA.

### D.2 — Concurrency model

Multiple workers/pod (gunicorn/uvicorn) **and** multiple pods; or **async** handlers for the I/O-bound stages (DB, Redis, LLM HTTP) — the pipeline is I/O-bound on LLM+DB, so async wins big. The audit append must stop serializing globally (per-tenant chain or ordered async writer).

### D.3 — LLM serving tier (the real throughput/latency killer)

Remove the `_OLLAMA_SEMAPHORE(1)` cap. Put a real tier behind the app: **vLLM/TGI with continuous batching across GPUs**, or a **managed API** with provisioned concurrency. Use the existing **complexity router** to keep cheap/cacheable queries off the big model; the Redis **semantic cache** absorbs repeats.

### D.4 — Latency budget (end-to-end SLO targets; tune to contract)

| Stage | Budget |
|---|---|
| dq_input · data_governance · cache · router · intent | < 5ms each |
| customer_memory · rag_retrieval | < 30ms |
| **agent / LLM** | cache hit < 10ms · else p50 ~300ms / p95 800ms / p99 1500ms |
| uncertainty_guard · dq_output | < 5ms |
| audit_trail (async or fast Postgres) | < 15ms |
| **end-to-end** | **p50 < 400ms · p95 < 900ms · p99 < 1.5s** (cache hits < 30ms) |

Gate every change with `loadtest/query_load.js` (k6).

### D.5 — Target topology (reference; requires D.1 first)

```yaml
# REFERENCE — do NOT scale `app` replicas before D.1 (stateless), or state diverges.
services:
  lb:         { image: nginx, ports: ["8080:80"] }              # round-robin → app
  app:        { build: ./backend, deploy: { replicas: 3 },      # stateless
                environment: [DATABASE_URL=…postgres…, REDIS_URL=…redis…, BRIDGE_AUTH=on] }
  db:         { image: postgres:16 }                            # audit + durable state
  cache:      { image: redis:7 }                                # cache / rate-limit / idempotency
  prometheus: { image: prom/prometheus }                        # scrape app /metrics
  grafana:    { image: grafana/grafana }                        # SLO dashboards
# LLM serving tier (vLLM/TGI multi-GPU, or managed API) sits behind `app` — see D.3.
```

### D.6 — Phased rollout (load-test gates each step)

1. Redis for cache + rate-limit + idempotency (smallest win; unblocks read-heavy multi-replica).
2. Postgres for audit (hardest — per-tenant hash-chain; migrate + verify before/after).
3. Push metrics to Prometheus; Grafana SLO dashboard.
4. Async / multi-worker + LB + ≥2 replicas.
5. LLM serving tier (batching / managed) + remove the semaphore cap.
6. Autoscale (HPA on rps + p95 latency).

### D.7 — What NOT to do

- Don't scale replicas before D.1 — divergent in-process state = wrong audit/metrics/cache.
- Don't put the big LLM in-process; keep it a separately-scaled tier.
- Don't micro-optimize the cheap stages — the LLM + audit write are the cost.
- SQLite stays correct for the single-node pilot; Postgres only when you actually scale (matches §8).

### D.8 — Measure first

`loadtest/query_load.js` ramps 12→460 rps (≈1M→10M/day). Run it against the current single node to see exactly where p95/p99 break and where 429s start — that's your baseline ceiling, and the gate for each step above.
