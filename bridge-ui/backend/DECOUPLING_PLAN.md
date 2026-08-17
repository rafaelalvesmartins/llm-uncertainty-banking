# Backend decoupling plan — server.py monolith → cohesive modules

> Incremental, behaviour-preserving. The git `main` branch (NIW exhibit) is untouched;
> work is on `product/bridge-platform`. Every step must keep all pytest + e2e green.

## The problem

`server.py` is a ~3600-line monolith holding four distinct concerns at once:
domain logic, in-memory + SQLite **state**, the LLM **backends**, and the 12-stage
**pipeline**. Every router reaches in via `_server()` and uses module-level names
(`apply_guard`, `classify_intent`, `_AUDIT`, `_GOVERNOR`, `_DQ_INPUT`, `_INTENT_CATALOG`,
`_RUNTIME_GUARD_THRESHOLD`, …); tests import `server` and use the same names.

## The shim pattern (how we decouple without breaking anything)

For each cohesive unit: **move the code to a new module, then re-export its names
from `server.py`** with a dual import:

```python
try:
    from core.guard import apply_guard, _extract_risk_level
except ImportError:                       # package-mode (backend.server)
    from backend.core.guard import apply_guard, _extract_risk_level
```

The `_server()` surface and every `server.X` reference keep resolving (now via the
re-export), so routers + the pipeline + tests change **zero**. Behaviour is identical
— this is structural only. Verify after each step: `pytest -q` (backend) + `npx playwright test` (frontend).

## Target module tree

| Module | Holds | Coupling |
|---|---|---|
| `core/guard.py` ✅ | `apply_guard`, `_extract_risk_level` | none (pure) |
| `core/classifier.py` ✅ | `classify_intent`, all 19 marker tuples/regexes, `detect_urgency_manipulation`, `_INTENT_KEYWORDS`, `_INTENT_CATALOG` | low (pure text + data) |
| `core/responses.py` ✅ | `_RESPONSES` (canned answer templates) | none (pure data leaf) |
| `backends.py` ✅ | `FakeBackend`, `OllamaBackend`, `_select_backend`, `_OLLAMA_*` infra, `_LLM_ALLOWED_INTENTS` | self-contained; imports `_RESPONSES` from the leaf (no cycle) |
| `models.py` ✅ | `QueryRequest`, `QueryResponse`, `PipelineStage`, `_AllowedChannel`, `_CUSTOMER_ID_PATTERN` | none (pure pydantic DTOs) |
| `state/audit.py` ✅ | `_AUDIT` deque, hash chain, SQLite, `_audit_append`, `_audit_db`, `_AUDIT_LOCK`, `_AUDIT_SEQ`, `_AUDIT_LAST_HASH` | **delicate** (chain integrity + lock) — solved via module-attribute proxy |
| `state/runtime.py` ✅ | `_percentiles`, `_STAGE_*`, `Metrics`/`_METRICS`, drift baseline (`_snapshot_for_baseline`, `_maybe_capture_baseline`, `_DRIFT_*`) | medium — proxy for the 3 drift scalars; `_CACHE`/`_RUNTIME_*` left in server.py |
| ~~`pipeline.py`~~ **stays in server.py** | the 12-stage `/query` + `/query/stream` orchestration | **composition root** — see below |

## ⚠️ Shim limitation discovered (coupling analysis, step 2→3 boundary)

The re-export shim is **only clean for pure / immutable units** (guard, classifier:
functions + frozen data, never rebound, never monkeypatched on `server`). A multi-agent
coupling map of the 4 remaining units surfaced a hard limit:

- **`state/audit.py` and `state/runtime.py` rebind module-level scalars** (`_AUDIT_SEQ`,
  `_AUDIT_LAST_HASH`; `_RUNTIME_GUARD_THRESHOLD`, `_RUNTIME_CACHE_ENABLED`, `_DRIFT_*`)
  that consumers read **and write on the `server` module**: `routers/audit.py` reads
  `s._AUDIT_SEQ`/`s._AUDIT_LAST_HASH`; `routers/settings.py` + `routers/drift.py`
  `setattr` the runtime scalars; and `test_a4_explain_tamper.py` / `test_b_visibility.py`
  do `server._AUDIT_SEQ = 0` **and** `monkeypatch.setattr(server, "_audit_db", ...)`.
  A plain `from state.audit import _AUDIT_SEQ` binds `server._AUDIT_SEQ` once at import;
  the mutator (now in `state.audit`) rebinds `state.audit._AUDIT_SEQ`, so `server`'s view
  goes **stale** — and a test writing `server._AUDIT_SEQ` no longer reaches the mutator.
  Re-export of a *rebound scalar read/written cross-module* is unsound.

- **`backends/`** has a circular hazard: `FakeBackend`/`OllamaBackend` call
  `_RESPONSES.get()` for fallbacks, but `_RESPONSES` must stay in `server.py` (agents +
  `_answer` use it). The backend module must not `import server`.

- **`pipeline.py`** is the capstone (depends on all of the above + the agent classes);
  only an orchestration-only "Stage A" slice is even a candidate, and only last.

**Conclusion:** steps 3–6 are **not** the clean verbatim-move the shim makes guard/classifier.
Each needs either a consumer-touching change or a module-attribute proxy.

### ✅ Resolution adopted: the module-attribute proxy (used for `state/audit.py`)

server.py installs a `_ProxyingServerModule` (a `types.ModuleType` subclass) at EOF and
registers the rebound/monkeypatched names in `_PROXIED_ATTRS` → owning sub-module:

- **`__getattr__`** (fires only on a normal-lookup MISS) returns `getattr(sub_module, name)`
  → `server._AUDIT_SEQ` always reads `state.audit`'s LIVE value.
- **`__setattr__`** delegates `server._AUDIT_SEQ = x` / `setattr(server, "_audit_db", fn)`
  to the sub-module → test writes + monkeypatches reach the real mutator.
- **Stable names** (shared `_AUDIT` deque, `_AUDIT_LOCK`, non-rebound fns) stay **plain
  re-exports** (same object, in `server.__dict__`).

Result: **routers and the 2 chain tests stay 100% unchanged**, so the same suite validates
the move. Verified: pytest 229, `/audit/verify` valid before+after with `head_seq` advancing
via the proxy, both import modes, e2e 27.

> **GOTCHA (cost ~2 iterations):** `__getattr__` is invoked for *attribute access on the
> module object* (`server.X`), **NOT** for **bare-name global lookups inside server.py's own
> functions**. server.py had one bare ref (`seq={_AUDIT_SEQ}` in the audit_trail stage) and a
> stray `_json_audit` alias the SSE handlers borrowed from the audit block — both raised
> `NameError` until pointed at `_audit_state_mod._AUDIT_SEQ` / a local `import json as
> _json_audit`. **Rule: any proxied name used by server.py's *own* code must be referenced via
> the sub-module (`_audit_state_mod.NAME`), never bare.** This applies to `state/runtime.py` next.

## Risk-ordered extraction sequence

1. **`core/guard.py` — DONE.** Pure functions, zero coupling. Verified pytest 229 + e2e 27.
2. **`core/classifier.py` — DONE.** `classify_intent` + all 19 marker tuples/regexes + `detect_urgency_manipulation` + `_INTENT_KEYWORDS` + `_INTENT_CATALOG`, moved as one contiguous unit (the markers were interleaved with the urgency detector, so cherry-picking 19 pieces was riskier than one block). The agent classes still in server.py (`_CallCenterAgent`/`_ChatbotAgent`) resolve the markers via the re-export; routers/tests use `server.classify_intent` / `server._INTENT_CATALOG`. Verified pytest 229 + e2e 27, both import modes, live `/query` routing (crisis/priv-esc/fraud/AML/non_pt) unchanged.
3. **`backends.py` + `core/responses.py` — DONE.** The circular hazard (`FakeBackend`/`OllamaBackend` call `_RESPONSES`, which the agents + `_answer` in server.py also need) was broken by first extracting `_RESPONSES` to the pure leaf `core/responses.py` (step 6a) and having BOTH server.py and backends import it from there → acyclic: `server → backends → core.responses`. Then moved FakeBackend/OllamaBackend/`_select_backend` + the Ollama circuit-breaker/queue infra + `_LLM_ALLOWED_INTENTS` to `backends.py` (step 6b). `_BACKEND = _select_backend()` stays in server.py. No proxy (the rebound `_OLLAMA` queue/breaker scalars are internal — reached only via re-exported functions). GOTCHA repeat: the moved block's inline `import os as _os_for_backend` was also used by server.py's CORS config → restored a local import. Verified pytest 229, live `/health`+`/integrations`+`/query`, e2e 27.
4. **`state/audit.py` — DONE.** The hash-chain store, moved as one contiguous block (875–1095) with its boot-time `_audit_restore_from_db()`. Rebound scalars (`_AUDIT_SEQ`/`_AUDIT_LAST_HASH`/`_AUDIT_DB`) + the monkeypatched `_audit_db` are **proxied** to `state.audit`; the shared deque/lock + non-rebound fns are plain re-exports. Verified pytest 229, `/audit/verify` valid before+after (`head_seq` 485→489 via proxy), both import modes, e2e 27. (Ordered before backends because it's a true leaf — no `import server`.)
5. **`state/runtime.py` — DONE.** Moved the cohesive observability block (`_percentiles` → `_maybe_capture_baseline`, lines 639–840) — metrics, per-stage latency, drift baseline. Scoped DOWN from the original plan: **`_CACHE` and `_RUNTIME_GUARD_THRESHOLD`/`_RUNTIME_CACHE_ENABLED` stayed in server.py** (pipeline controls, interleaved with `_FEEDBACK`/`_COMPLEXITY`, already consistent intra-module — no gain in moving). Proxied the 3 drift scalars setattr'd by routers/drift.py (`_DRIFT_BASELINE`, `_DRIFT_LAST_AUTO_REBASELINE_AT_QUERY`, `_DRIFT_AUTO_REBASELINE_EVERY`); the rest plain re-exports. `_PROXIED_ATTRS` is now defined once at the runtime shim (earliest) and reused by the audit shim. Verified pytest 229, live `/metrics` + `POST /drift/baseline`→`GET /drift` round-trip (proxy write+read) + `/audit/verify`, e2e 27.
6. **API DTOs → `models.py` — DONE (step 7).** `QueryRequest`/`QueryResponse`/`PipelineStage` + the channel/customer-id validators. Pure pydantic, clean leaf, re-exported. Verified pytest 229, live `/query`, e2e 27.
7. **`pipeline.py` — DELIBERATELY NOT EXTRACTED.** `query` (~310 lines) + `query_stream` are the **composition root**: they reference 30+ server.py names (every state singleton, the agents, `_answer`, `classify_intent`, `apply_guard`, audit/metrics, runtime controls). Extracting them would force rewriting the core `/query` path so every dependency is reached via a lazy `s.` accessor — high risk on the most critical path, and it does NOT reduce coupling, it just relocates the orchestration and ADDS `s.` indirection. The orchestration *belongs* with the composition root. Leaving it in server.py is the correct call (matches the analysis's `safe_to_extract_now: false`).

## Status

- Step 1 (guard) ✅, Step 2 (classifier) ✅ — clean shim candidates (pure logic / frozen data).
- **Step 3 (`state/audit.py`) ✅** — first STATEFUL extraction; the module-attribute proxy
  solved the rebound-scalar problem with **zero consumer changes**.
- **Step 5 (`state/runtime.py`) ✅** — metrics/drift observability block; same proxy for the 3 drift scalars.
- **Step 6 (`core/responses.py` + `backends.py`) ✅** — broke the circular `_RESPONSES` hazard via a leaf, then moved the LLM backends.
- **Step 7 (`models.py`) ✅** — extracted the API-contract DTOs. server.py 3573 → **1995 lines (−1578, −44%)**.
- **DONE.** 7 focused modules extracted (`core/{guard,classifier,responses}`, `backends`, `models`, `state/{audit,runtime}`).
  `pipeline.py` deliberately NOT extracted — the `/query` orchestration is the composition root and belongs in server.py.

## Final architecture

server.py is no longer a god-file; it is the **composition root** that wires together the extracted modules:
- **`core/`** — pure domain logic + data: `guard` (uncertainty decision), `classifier` (intent + 19 safety markers + catalog), `responses` (canned answers).
- **`backends.py`** — the LLM backends (Fake/Ollama) + selection + Ollama resiliency; imports `core.responses` (acyclic).
- **`models.py`** — the API-contract pydantic DTOs.
- **`state/`** — the mutable stores: `audit` (BCB-4893 hash chain + SQLite) and `runtime` (metrics/drift), exposed live to the `server.X` surface via the module-attribute proxy.
- **server.py keeps**: the FastAPI app + middleware, the agent classes + `_answer` dispatch, the remaining pipeline-component singletons (`_DQ_*`, `_GOVERNOR`, `_RAG`, `_CACHE`, `_RATE_LIMITER`, `_CUSTOMER_MEMORY`, …), the 12-stage `/query`/`/query/stream` orchestration, the runtime controls (`_RUNTIME_*`), and route registration.

Two reusable patterns came out of this: the **re-export shim** (pure/immutable units) and the **module-attribute proxy** (`_PROXIED_ATTRS` + `_ProxyingServerModule`) for stateful units whose rebound scalars are read/written cross-module. Every step verified: pytest 229, e2e 27, both import modes, and (for audit) the `/audit/verify` chain gate.
