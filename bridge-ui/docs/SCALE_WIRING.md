# SCALE_WIRING.md — Human-Verified Wiring Guide for Track D

> **REFERENCE artifact — 2026-06-14.**
> These are the exact, human-verified steps required to swap each in-process
> singleton for its external-store adapter before you may safely run
> `deploy.replicas > 1` in `docker-compose.scale.yml`.
>
> **The app is NOT stateless today.**  Every step below has a mandatory
> load-test gate.  Complete them in order; do not skip ahead.  The demo path
> (`BRIDGE_AUTH=off`, single node) keeps working at all times — every change
> is additive and flag-gated.
>
> **Wiring order matches D.6 in `ENGINEERING_HARDENING_PLAN.md`:**
> 1. Redis cache + rate-limiter + idempotency
> 2. Postgres audit store  ← LOUD step: validate chain before trusting
> 3. Prometheus /metrics
> 4. Multi-worker / LB (≥2 replicas)
> 5. LLM serving tier
> 6. Autoscale

---

## Prerequisites

- `docker-compose.scale.yml`, `nginx.conf`, `prometheus.yml`, and
  `backend/Dockerfile` are created (this is the reference infra package).
- A Docker environment is available.
- `POSTGRES_PASSWORD` and `GRAFANA_PASSWORD` are set in `.env` (copy
  `.env.example`).
- `loadtest/query_load.js` (k6) exists and runs against `http://localhost:8080`.
- The safety-smoke suite passes on the current single-node deploy:
  `cd bridge-ui/backend && pytest test_safety_smoke.py -v`

---

## Step 1 — Redis: Semantic Cache, Rate-Limiter, Idempotency

**Why first:** these are the smallest, most reversible wins.  A Redis miss
falls back to the in-process cache, so early wiring errors are non-fatal.

### Adapter modules (created by other agents)
- `scale/cache_redis.py` — `RedisSemanticCache` / `get_cache(fallback)`
- `scale/limiter_redis.py` — Redis token-bucket rate-limiter
- `scale/idempotency_redis.py` — `get_idempotency_store(fallback)` (if exists)

> **⚠️ Behavioral divergence — rate limiter (verify before relying on it as a drop-in).**
> `scale/limiter_redis.py` enforces a **fixed 1-second window** (N requests per
> calendar second), whereas the in-process limiter is a **token bucket** (smooth
> refill + burst allowance). They are *not* request-for-request equivalent: at a
> window boundary the Redis limiter can admit up to ~2×`BRIDGE_BURST` in a short
> span, and it does not carry unused allowance forward the way the bucket does.
> Before flipping production traffic to it: (a) decide whether fixed-window is
> acceptable for your SLA, or port the token-bucket algorithm into the Lua
> script; and (b) note `fakeredis` has no `EVALSHA`, so the Lua-path tests are
> capability-skipped locally and only run against a real Redis — exercise them in
> a staging environment before trusting the limiter under load.

### server.py changes

**File:** `bridge-ui/backend/server.py`

1. Near the `_CACHE` initialization (search for `SemanticCache()`):

   ```python
   # BEFORE
   _CACHE: SemanticCache = SemanticCache(...)

   # AFTER — flag-gated
   from scale.cache_redis import get_cache as _get_redis_cache
   _CACHE = _get_redis_cache(SemanticCache(...))
   ```

2. Near the `_RATE_LIMITER` initialization (search for the in-process
   rate-limiter constructor):

   ```python
   # BEFORE
   _RATE_LIMITER = <InProcessRateLimiter>(...)

   # AFTER — flag-gated
   from scale.limiter_redis import get_limiter as _get_redis_limiter
   _RATE_LIMITER = _get_redis_limiter(_RATE_LIMITER)
   ```

3. If an idempotency cache exists, apply the same `get_idempotency_store`
   factory pattern.

### Env flag

Set `REDIS_URL=redis://cache:6379/0` in the app environment (or locally in
`.env`).  Without `REDIS_URL`, all three factories return the existing
in-process objects unchanged.

### Tests to run

```bash
# Unit/integration (fakeredis — no real Redis needed)
pytest bridge-ui/backend/scale/test_cache_redis.py -v

# Safety-smoke + cache-scope confidentiality regression
pytest bridge-ui/backend/test_safety_smoke.py \
       bridge-ui/backend/test_cache_confidentiality.py -v

# Load test (requires k6 and a running stack)
k6 run --env BASE_URL=http://localhost:8080 loadtest/query_load.js
# Gate: p95 < 900ms, 0 audit-chain breaks, 0 cross-scope cache hits.
```

### Rollback

Unset `REDIS_URL`.  All three factories return the in-process objects.
No data migration needed.

---

## Step 2 — Postgres: Audit Store

> ## !! LOUD STEP — READ THIS BEFORE TOUCHING server.py !!
>
> The audit store holds the tamper-evident hash-chain that is the core
> compliance claim of the Bridge platform.  Migrating it incorrectly will
> silently produce a second chain that disagrees with the SQLite chain.
> A regulator sees that as evidence of tampering.
>
> **Do NOT wire the Postgres adapter until the pre-migration validation
> below passes.**

### Adapter module
- `scale/audit_postgres.py` — Postgres append-only audit writer / verifier

### Pre-migration validation (MANDATORY)

Run `test_audit_disk_integrity.py` against the existing SQLite store
BEFORE starting the migration.  This test re-verifies the full persisted
chain via `GET /audit/verify?source=disk`.  If it fails, the SQLite chain
is already broken and you must investigate before proceeding.

```bash
# Must pass with 0 failures before you touch anything.
pytest bridge-ui/backend/test_audit_disk_integrity.py -v
```

Also run the concurrent-append test to confirm the existing chain holds
under load:

```bash
pytest bridge-ui/backend/test_audit_concurrency.py -v
```

### Migration plan

1. Start the Postgres service (`docker compose -f deploy/docker-compose.scale.yml up db`).
2. Run the schema migration in `scale/audit_postgres.py` (or the SQL in
   `reference/gateway/init.sql` adapted for the `audit_entries` table).
3. Export the existing SQLite entries and import them into Postgres, preserving
   the hash-chain sequence and all HMAC values exactly.
4. Run `GET /audit/verify?source=disk` against the SQLite store AND then the
   same endpoint pointed at Postgres.  Both must return `chain_valid: true`
   and agree on `total_entries` and the final `chain_hash`.

### server.py changes

**File:** `bridge-ui/backend/server.py`

Near the `_AUDIT` initialization (search for `AuditStore` or `_AUDIT_LOCK`):

```python
# BEFORE
_AUDIT: AuditStore = AuditStore(...)   # SQLite, in-process lock

# AFTER — flag-gated
from scale.audit_postgres import get_audit_store as _get_pg_audit
_AUDIT = _get_pg_audit(fallback=AuditStore(...))
```

All call-sites in `server.py` that write to `_AUDIT` or acquire `_AUDIT_LOCK`
must route through the adapter's interface.  The Postgres adapter uses
`INSERT ... RETURNING` under a `psycopg` async connection — the global
`_AUDIT_LOCK` is no longer needed when the adapter is active (Postgres
serializes appends per-tenant natively), but keep the lock guard in the
fallback path so the SQLite path is unchanged.

### Env flag

`DATABASE_URL=postgresql://bridge:<password>@db:5432/bridge`

Without this, `get_audit_store` returns the SQLite `AuditStore`.

### Tests to run

```bash
# Validate Postgres chain against SQLite chain — MUST pass.
pytest bridge-ui/backend/test_audit_disk_integrity.py -v

# Concurrent-append test against Postgres adapter.
pytest bridge-ui/backend/test_audit_concurrency.py -v

# Full safety-smoke.
pytest bridge-ui/backend/test_safety_smoke.py -v

# Load test with audit-monotonic check.
k6 run --env BASE_URL=http://localhost:8080 loadtest/query_load.js
# Gate: 0 chain breaks (monotonic seq + valid HMAC), p95 audit write < 15ms.
```

### Rollback

Unset `DATABASE_URL`.  The `get_audit_store` factory returns the SQLite store.
SQLite entries are untouched (the Postgres writer never wrote to SQLite).

---

## Step 3 — Prometheus: /metrics Endpoint

**Why here:** metrics are read-only from the app's perspective; wiring them
after the storage adapters means the counters reflect real traffic.

### Adapter module
- `scale/metrics_prometheus.py` — Prometheus-client counter/histogram
  definitions
- `routers/observability.py` — mounts `GET /metrics` on the FastAPI app

### server.py changes

**File:** `bridge-ui/backend/server.py`

1. Mount the observability router (near the other `app.include_router` calls):

   ```python
   from routers.observability import router as observability_router
   app.include_router(observability_router)
   ```

2. Instrument the pipeline stages — in the `/query` handler and other hot
   paths, call the counter/histogram helpers from `scale/metrics_prometheus.py`:

   ```python
   from scale.metrics_prometheus import (
       record_request,
       record_latency,
       record_cache_hit,
       record_guard_block,
   )
   ```

   Wrap the relevant `try/finally` blocks in the existing pipeline stages.

### Env flag

No env flag required — the router is always mounted once included.  If you
want to gate it, guard `app.include_router(observability_router)` behind
`if os.getenv("PROMETHEUS_ENABLED", "true") == "true"`.

### Tests to run

```bash
# Verify /metrics returns 200 and contains expected metric names.
pytest bridge-ui/backend/test_b_visibility.py -v   # existing visibility tests
# Manually: curl http://localhost:8000/metrics | grep bridge_requests_total

# Confirm Prometheus scrapes successfully.
# docker compose -f deploy/docker-compose.scale.yml up prometheus
# curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets'
```

### Rollback

Remove `app.include_router(observability_router)` from `server.py`.  The
`/metrics` endpoint disappears; Prometheus scrape returns 404 (harmless).

---

## Step 4 — Multi-worker / Load Balancer (≥2 Replicas)

> **Gate:** Steps 1–3 must be complete and load-tested before this step.
> Running replicas > 1 while any in-process state remains will diverge state
> across replicas silently.

### Checklist before bumping replicas

- [ ] `REDIS_URL` is set; cache + limiter + idempotency route through Redis adapters.
- [ ] `DATABASE_URL` is set; audit appends go to Postgres.
- [ ] `GET /audit/verify?source=disk` against Postgres returns `chain_valid: true`.
- [ ] `test_audit_disk_integrity.py` passes against Postgres.
- [ ] `test_cache_confidentiality.py` passes.
- [ ] Load test at 1 replica passes all gates.

### docker-compose.scale.yml change

In `bridge-ui/deploy/docker-compose.scale.yml`, change:

```yaml
# BEFORE
deploy:
  replicas: 1   # (or comment this out entirely)

# AFTER
deploy:
  replicas: 3
```

### Dockerfile CMD change

Once the app is stateless, enable multi-worker mode in `backend/Dockerfile`:

```dockerfile
# BEFORE
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# AFTER
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

Four workers per container is a safe default for I/O-bound FastAPI; tune
against the load-test results.

### Tests to run

```bash
# Load test with 3 replicas behind nginx lb.
k6 run --env BASE_URL=http://localhost:8080 loadtest/query_load.js
# Gates:
#   p50 < 400ms, p95 < 900ms, p99 < 1500ms
#   0 audit chain breaks
#   0 cross-scope cache hits
#   0 duplicate idempotency keys served by different replicas

# Verify audit chain is single, monotonic, and valid across all replicas.
# All replicas write to the same Postgres; there is one chain per tenant.
curl http://localhost:8080/audit/verify?source=disk
# Expect: {"chain_valid": true, ...}
```

### Rollback

Set `replicas: 1` in the compose file.  Nginx continues routing to a single
backend.  No state migration needed.

---

## Step 5 — LLM Serving Tier

**Why last in functional wiring (before autoscale):** the LLM tier requires
GPU resources or a managed API contract that is external to this repo.  Wire
it only after the app itself is stateless and horizontally scaled.

### Change

In `docker-compose.scale.yml` (or a separate `docker-compose.llm.yml`), add:

```yaml
services:
  llm:
    image: vllm/vllm-openai:latest   # or ghcr.io/huggingface/text-generation-inference
    # ...GPU/model config...
```

In `server.py` / `backends.py`, update `OLLAMA_URL` / `LUB_BACKEND` to point
to the new tier.  Remove or raise the `_OLLAMA_SEMAPHORE(1)` cap (it exists
to protect a single Ollama process; vLLM/TGI handle concurrency internally).

See `ENGINEERING_HARDENING_PLAN.md §D.3` for topology details.

### Tests to run

```bash
# Resilience tests against the new LLM endpoint.
pytest bridge-ui/backend/test_ollama_resilience.py -v

# Full load test at the 10M/day target (460 rps peak).
k6 run --env BASE_URL=http://localhost:8080 \
       --env TARGET_RPS=460 \
       loadtest/query_load.js
# Gate: p95 < 900ms, LLM p50 < 300ms, breaker trips at correct failure rate.
```

### Rollback

Revert `OLLAMA_URL` to the single-node Ollama endpoint.  Re-lower the
semaphore cap.

---

## Step 6 — Autoscale

**Kubernetes only.** At this point the app is stateless and horizontally
scaled — standard HPA applies.

```yaml
# k8s/hpa.yaml (reference, not included in this repo)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: bridge-app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: bridge-app
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
    - type: Pods
      pods:
        metric:
          name: bridge_request_latency_p95_seconds
        target:
          type: AverageValue
          averageValue: "0.9"   # p95 < 900ms SLO
```

Prometheus Adapter must expose `bridge_request_latency_p95_seconds` as a
custom metric.  Grafana SLO dashboard (`reference/monitoring/`) shows this
alongside rps and error rate.

---

## Adapter Module Quick-Reference

| Adapter | Module | Replaces | Flag env var |
|---|---|---|---|
| Redis semantic cache | `scale/cache_redis.py` | `_CACHE` (in-process `SemanticCache`) | `REDIS_URL` |
| Redis rate-limiter | `scale/limiter_redis.py` | `_RATE_LIMITER` (in-process) | `REDIS_URL` |
| Redis idempotency | `scale/idempotency_redis.py` | in-process idempotency dict | `REDIS_URL` |
| Postgres audit | `scale/audit_postgres.py` | `_AUDIT` + `_AUDIT_LOCK` (SQLite) | `DATABASE_URL` |
| Prometheus metrics | `scale/metrics_prometheus.py` + `routers/observability.py` | `_METRICS` in-process counters | (always on when mounted) |

---

## Anti-patterns (matches ENGINEERING_HARDENING_PLAN.md §D.7)

- **Do NOT** bump `replicas > 1` before Steps 1–3 are done.  The compose file
  ships with replicas: 3 as the target topology; set it to 1 until ready.
- **Do NOT** extract the `/query` pipeline into a separate service.  It is the
  composition root; extraction relocates coupling without removing it.
- **Do NOT** migrate to Postgres for the single-node pilot.  SQLite-WAL is
  correct for that use case.  Postgres is triggered by concurrency/HA need.
- **Do NOT** wire `BRIDGE_AUTH=on` before Track C (C1→C3) multi-tenant
  isolation is complete — see `ENGINEERING_HARDENING_PLAN.md §C ordering guardrail`.
