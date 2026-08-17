# Bridge Platform — Architecture Review

> Generated 2026-06-14 by a multi-agent audit (8 dimensions reviewed in parallel, every
> high/critical finding adversarially verified against the code before inclusion).
> 29 agents - 0 findings refuted, most 'criticals' downgraded to documented demo gaps;
> two genuine present-tense defects survived (see R1, R2).

---

## Resolution log (2026-06-14, same session)

| Item | Status | Commit |
|---|---|---|
| **R1** — semantic cache cross-customer leak | ✅ fixed (scope by customer_id + regression test) | `e22242f` |
| **R2** — audit chain verified only at boot | ✅ fixed (`/audit/verify?source=disk` re-validates persisted rows + test) | `e22242f` |
| **R3** — proxy registration could drift silently | ✅ fixed (import-time assertion) | `e22242f` |
| SQLite WAL hardening | ✅ done | `e22242f` |
| **R4a** — Ollama breaker lock-free RMW | ✅ fixed (`_OLLAMA_BREAKER_LOCK`) | `432b0de` |
| **R4b** — no concurrency test on `_AUDIT_LOCK` | ✅ added (8×10-thread load test) | `432b0de` |
| SoD-off honesty signal | ✅ added (`sod_enforced`/`sod_warning` on decisions) | `8e5e4ab` |
| **R4c** — CI gate (GitHub Actions) | ⏸ deferred — infra decision for the repo owner (a pre-commit safety gate already exists) |  |
| Queue-depth TOCTOU (`server.py:965`) | ⏸ skipped — minor soft-cap on the untested real-Ollama path, bounded by `Semaphore(1)` |  |
| `.env.example` creds + secret scan; cross-platform temp path; UI display of `sod_warning` | ⏸ minor / nice-to-have |  |
| **Step 7** production phases (tenant_id isolation, KMS, Postgres, deploy) | ⏸ documented & deferred in PRODUCT_PLAN_V6 |  |

Tests after fixes: **234 pytest + 27 e2e + 148 lub cache**, all green.

---

# Bridge Platform — Architecture Review

## 1. Executive Summary & Health Verdict

Bridge is a **well-engineered, intellectually honest demonstrator** of model-risk governance, not a production banking system — and that distinction is the key to reading every finding below. The recent decoupling of a 3,573-line monolith into 7 cohesive modules (guard, classifier, responses, backends, models, state/audit, state/runtime) is genuinely clean: an acyclic import graph, a well-motivated module-attribute proxy for rebound scalars, and a uniform lazy-accessor pattern across ~19 routers. The cryptographic primitives are real (EdDSA JWT, SHA-256 hash-chained audit, Ed25519 evidence signing), and the team documents its gaps unusually well (DEMO_SCOPE.md, PRODUCT_PLAN_V6.md phase roadmap).

The adversarial verification round did its job: **of the 4 "critical"/"high" headline findings, none survived at the stated severity.** Most were downgraded because reviewers scored a single-worker, documented-single-tenant demo against a multi-worker production deployment that the codebase explicitly disclaims. The reviewers who "cried wolf" most loudly were `prod` and `data` (multiple criticals/highs corrected to medium/low) and `security` (the ephemeral-key "high" collapsed to *none* — it is correct demo design with the public key embedded in every package).

That said, two findings survive verification as **genuine, present-tense architecture defects** that exist regardless of deployment topology and deserve fixing before the next demo iteration: the **semantic-cache cross-customer answer leak** and the **audit chain's disk integrity being verified only once at startup**. These are not "future production" problems — they are wrong in the demo as it runs today.

**Overall verdict: HEALTHY for its stated scope (demo / regulatory exhibit).** Weighted health ≈ **3 / 5**. The architecture is sound; the residual real risks are narrow and fixable in days, not quarters.

## 2. Per-Dimension Health Scores

| Dimension | Score | One-line read |
|---|---:|---|
| Module & Dependency Architecture | 4 | Clean decoupling; only minor proxy-registration drift risk. |
| Runtime | 3 | Sync-only, GIL-reliant; the one "high" is a documented single-worker constraint. |
| Security | 2 | Real crypto, but cache-leak + at-rest audit verification are real; headline criticals over-stated. |
| Data | 2 | Genuine semantic-cache leak; most "highs" are production-scoped, not demo-real. |
| API | 3 | Coherent routers; both "highs" downgraded to demo-intentional. |
| Frontend | 3 | Honest LIVE/MOCK labeling; polling burst real but narrower than claimed. |
| Testing | 3 | Strong safety moat; real gaps in Ollama/concurrency/CI coverage (all confirmed). |
| Prod | 2 | Infra gaps real but documented/deferred; the one survivor is the cache leak again. |

## 3. Genuine Strengths

- **Disciplined decoupling.** The two-pattern strategy — re-export shims for immutable units, a module-attribute proxy (`_ProxyingServerModule.__getattr__/__setattr__`) for rebound scalars like `_AUDIT_SEQ` / `_DRIFT_BASELINE` — is well-motivated, correctly implemented, and transparent to test monkeypatching. The documented "bare reference" gotcha is fixed (`server.py:1378`). Acyclic import graph (`backends → core.responses → server`).
- **Real, not mock, cryptography.** EdDSA-signed JWT with signature + expiry verification (`auth.py:75-85`); SHA-256 hash-chained audit persisted to SQLite (`state/audit.py:168-233`); Ed25519 evidence packages that embed the public key, so any package is independently verifiable even after restart.
- **A real safety moat in tests.** The 6-spot-sync rule with 32 parametrized safety cases + innocent baselines (`test_safety_smoke.py`) catches marker desynchronization across `classify_intent → apply_guard → agent dispatch` automatically. Test isolation via monkeypatch/global snapshot is rigorous.
- **Honesty as an architectural property.** `featureMap.ts` is a single source of truth for LIVE/MOCK/STATIC; `HowThisWorks` cross-checks declared endpoints against live `/openapi.json` to prevent silent drift. DEMO_SCOPE.md and PRODUCT_PLAN_V6.md name every gap and phase-order the fixes (auth → tenancy → persistence → ops).
- **Correct concurrency where it counts.** The Ollama queue depth is guarded (`enter()` before semaphore wait, `exit()` in `finally`), and audit appends are serialized under `_AUDIT_LOCK`. The idempotency and rate-limit caches are correctly keyed by `(customer_id, …)`.

## 4. The Real Risks (confirmed / nuanced only)

### 4a. Real architecture issues — wrong *today*, regardless of deployment

**R1 — Semantic cache leaks one customer's answer to another (HIGH).**
*Verdict: confirmed (data), corrected to high; resurfaces as the true core of the prod "critical".*
`_CACHE = SemanticCache(...)` (`server.py:331`) is a single global instance. `_CACHE.lookup(req.query)` (`server.py:1092`) passes **only query text, no `customer_id`**; `memory.py:155-196` returns the best embedding match regardless of customer. Verification reproduced it: Customer B issuing "Qual é o saldo?" got Customer A's cached answer at similarity 1.0, because that query classifies as INTERNAL (not RESTRICTED), so the existing PII/RESTRICTED cache bypass (`server.py:1086-1091`) does not fire. This is a confidentiality leak in the running demo, not a hypothetical.
**Fix:** key cache entries on `(tenant_or_customer_scope, query_normalized)`. Minimum viable: thread a scope string into `lookup()`/`store()` and compare it before returning a hit. Add a regression test: tenant-A entry must not be hit by tenant-B on an identical query.

**R2 — Audit chain at rest is verified only once, at startup (HIGH).**
*Verdict: confirmed (security), severity held at high.*
The disk chain is validated by `_audit_chain_break()` only during `_audit_restore_from_db()` at import (`audit.py:103-166`, `:241`). `/audit/verify` (`audit.py:118-183`) re-checks **only the in-memory deque**, and `/audit/export?source=disk` (`audit.py:186-254`) reads SQLite (`:204-215`) **without** re-running chain validation. The code comment at `audit.py:113` claiming runtime `/audit/verify` catches a real in-place disk tamper is **incorrect** — it never re-reads disk. So a file-system-level `UPDATE audit_entries …` between restarts persists undetected. For a product whose entire thesis is tamper-evident auditability, this is the most important *correctness* gap.
**Fix:** make `/audit/verify` and `/audit/export?source=disk` call `_audit_chain_break()` against the persisted rows, not just memory. Correct the misleading comment at `audit.py:113`. (Cheap, high-leverage, no infra dependency.)

**R3 — Proxy registration is manual and can drift silently (MEDIUM).**
*Verdict: confirmed (module architecture).*
`_PROXIED_ATTRS` (`server.py:261-262, 324-325`) is hand-populated; a new rebound scalar added to `state/audit.py`/`state/runtime.py` but not registered yields `None`/AttributeError only when first read.
**Fix:** tie registration to the source module (`{_runtime_state_mod: ['_DRIFT_BASELINE', …]}`) and assert at import that every name resolves. Optionally a pre-commit grep for bare proxied-name references in `server.py`.

**R4 — Test coverage holes on the real-LLM and concurrency paths (HIGH, three confirmed).**
*Verdict: confirmed (testing), held at high.*
(a) `OllamaBackend` (`backends.py:156-312`) — circuit breaker, queue semaphore, timeout — has **zero** unit coverage; `test_integrations.py:31` monkeypatches `_ollama_status()` away. The breaker's compound mutation (`_ollama_record_failure`, `backends.py:102-112`) writes `_OLLAMA_BREAKER_OPEN_UNTIL` and clears the deque **without a lock** — a real (if low-probability) race the tests can't see. (b) The only concurrency test (`test_a3_bugfixes.py:121-180`) targets an already-fixed `/stats` deque bug; the `/query` pre-flight queue check reads `_ollama_queue_depth()` **without the lock** (`server.py:965`), a TOCTOU that can let depth exceed the 429 threshold under load — never exercised. (c) No CI gate: the `--cov-fail-under=80` workflow is the `lub` library's only; `bridge-ui/` has no `.github/workflows`, no pre-commit, so a 6-spot-sync regression can land unblocked.
**Fix:** add opt-in real-Ollama tests (gated by env, skipped in CI) for breaker/queue/timeout; a small lock around the breaker's read-modify-write; a 10–50-thread `/query` load test asserting queue depth ≤ max and monotonic audit seq; and a GitHub Actions job running `pytest` + Playwright on every PR with a pre-commit hook for the safety suite.

### 4b. Intentional demo gaps the team already documents (do not re-litigate as bugs)

These are real *only* under a deployment the codebase explicitly disclaims (multi-worker, multi-tenant, BRIDGE_AUTH=on with real users). They belong on the PRODUCT_PLAN_V6 roadmap, **not** the defect list.

- **Segregation-of-duties bypass when `BRIDGE_AUTH=off`** (security, critical→**medium**): the SoD check compares two body-supplied strings, but this is the documented Phase-1 demo fallback; Phase-1 auth (`verify_token`, EdDSA validation, the `test_authenticated_identity_overrides_spoofed_body` test) already exists for `=on`. *One real residual:* the control flow *looks* like it validates independent reviewers, which could mislead. **Cheap mitigation worth taking now:** when auth is off, have `/governance/changes/*/decision` return 503 or stamp the response/UI with "SoD not enforced (BRIDGE_AUTH=off)".
- **Unprotected idempotency cache / metrics / SemanticCache thread-safety under multi-worker** (runtime, high→**low**): correct under the documented single uvicorn worker; GIL serializes the hot paths.
- **SQLite `check_same_thread=False` without WAL** (data, high→**low**): single-worker + `threading.Lock` is sufficient as documented; production targets Postgres. *(WAL is still a near-free hardening — enable it.)*
- **No `tenant_id` columns** (data, high — confirmed but Phase-3 scoped): a real schema gap that becomes a leak **only if** Phase-1 auth ships without Phase-3 isolation. The fix sequencing ("don't wire auth before tenant columns") is the actionable part.
- **Idempotency-cache "memory leak"** (data, high→**low**): 60s TTL + demo session lengths make OOM-in-weeks unrealistic; siblings use bounded deques, so it's an inconsistency, not a hazard.
- **Hardcoded demo credentials** (security, high→**medium**): real residual only if someone sets `BRIDGE_AUTH=on` without rotating; gated off by default, Phase-2 hashing planned. Still: move to `.env.example` and add a pre-commit secret check.
- **Auth only on governance endpoints** (api, high→**low**) and **ephemeral signing keys** (security, high→**none**): both explicitly documented Phase-1 demo scope; the ephemeral-key finding is actively *wrong* (public key travels in every package → verification never needs the private key). **Reviewer cried wolf here.**
- **Single uvicorn worker / no structured logging / no KMS / no Dockerfile** (prod, high→**medium/low**): all documented, phase-ordered infrastructure deferrals, not architecture defects.
- **DELETE proxy skips `r.ok`** (api, high→**low**): the cited 409 path doesn't exist; backends always return 200. Tidy for consistency, not urgent. **Reviewer over-stated.**
- **Polling load spikes** (frontend, high→**medium**): real but it's 5–6 panels on one tab, not the claimed 18 across all tabs. **Scope inflated.**

## 5. The Single Biggest Architectural Risk

**The semantic-cache cross-customer answer leak (R1).** It is the only confirmed defect that (a) violates the product's core promise — correct, isolated, governed answers — (b) is reproducible in the demo *as it runs today* with no exotic deployment, and (c) would be acutely embarrassing in front of the exact audience (regulators/risk reviewers) the demo targets. The `prod` reviewer correctly identified this as the *true* critical hiding inside the over-broad "no multi-tenant isolation" finding: the architectural-tenancy planning is appropriately deferred, but the global cache keyed solely on query text is a present-tense bug. It is also among the cheapest to fix.

## 6. Prioritized, Sequenced Roadmap

Do these in order; each is gated on the previous only where noted.

1. **Scope the semantic cache (R1).** Add a customer/tenant scope to `lookup()`/`store()` in `memory.py` + `server.py:1092`; add a cross-tenant cache-miss regression test. *Verify:* B cannot read A's cached answer on an identical query. **(~1 day, highest impact.)**
2. **Make audit integrity verifiable at rest (R2).** Have `/audit/verify` and `/audit/export?source=disk` re-run `_audit_chain_break()` over persisted rows; fix the false comment at `audit.py:113`. *Verify:* an out-of-band SQLite `UPDATE` is detected by `/audit/verify` without a restart. **(~1 day.)**
3. **Stand up a CI gate for `bridge-ui` (R4c).** GitHub Actions: `pytest` + Playwright on every PR; pre-commit hook running the safety smoke suite. *Verify:* a deliberate 6-spot-sync break fails CI. **(~1 day; protects everything after.)**
4. **Cover the real-LLM and concurrency paths (R4a/b).** Opt-in Ollama tests (breaker/queue/timeout); lock the breaker's read-modify-write (`backends.py:102-112`); move the `/query` queue-depth check under the lock (`server.py:965`); a 10–50-thread `/query` load test. *Verify:* queue depth never exceeds max; audit seq stays monotonic; chain verifies post-run.
5. **Harden the proxy registration (R3).** Source-module-keyed `_PROXIED_ATTRS` + import-time assertion. *Verify:* registering a scalar without listing it fails at import, not at first read.
6. **Cheap demo-honesty + hardening wins** (parallelizable): enable SQLite WAL; when `BRIDGE_AUTH=off`, surface "SoD not enforced" on governance decisions; move demo credentials/personas to `.env.example` + pre-commit secret scan; cross-platform temp path via `tempfile.gettempdir()`.
7. **Then, and only then, the documented production phases** in PRODUCT_PLAN_V6 order — **Phase 1 auth must not ship before Phase 3 adds `tenant_id` columns and `WHERE tenant_id=?` everywhere** (this ordering is itself the mitigation for the confirmed schema-gap finding). KMS/HSM (Phase 4), structured logging + correlation IDs (Phase 6), containerization (Phase 6) follow.

**Bottom line:** steps 1–6 are days of work and close every *real* defect; step 7 is the legitimately deferred road to production that the team has already mapped. The architecture is in good shape — finish the short list before the next demo, and don't let the over-stated criticals distract from the two that actually matter.
