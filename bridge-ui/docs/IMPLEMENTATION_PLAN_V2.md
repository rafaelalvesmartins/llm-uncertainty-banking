# Bridge Console — Implementation Plan v2 (verified, handoff-ready)
### create → stage → approve → deploy → monitor

> Hand this whole file to the executing LLM. It is self-contained: it assumes **no** prior
> conversation. Every "VERIFIED" claim was checked against the code on 2026-06-17.
> It supersedes `IMPLEMENTATION_PLAN.md`; the corrections (intent is **not** writable;
> "deploy" needs a per-kind read-site; the cheapest first kind is a **runtime-control
> policy**, not intent) are load-bearing — do not revert to the old assumptions.

> **Verification log — 2026-06-17 (checked against source, not memory):**
> - `apply_guard(confidence, threshold=0.7, intent="", risk_level=0.0)` is pure — `core/guard.py:37`.
> - `_RUNTIME_GUARD_THRESHOLD` / `_RUNTIME_CACHE_ENABLED` defined `server.py:337-338`; read each `/query` (`server.py:1113,1280` guard · `1085,1298,1306` cache); written by `PUT /settings` (`routers/settings.py:94-96`); also read by `model_card.py:46`, `security.py:93`, `visibility.py:428,616`.
> - `_INTENT_CATALOG: Final[...]` hard-coded `core/classifier.py:784`, no writer; readers = discovery/experiments/audit/calibration; `classify_intent` (`classifier.py:658`) does **not** read it.
> - Change store has `submit`/`list`/`decide` but **no apply** — `routers/governance_changes.py`.
> - Provider registry exists but is **not** wired into `_select_backend()` — `core/providers.py`.

---

## 0. READ FIRST — this repo's operational hazards (skip these and you WILL corrupt work)

1. **Monorepo + dormant CI.** Git root = `c:/code/eb2niw`. The app lives at
   `09_Projeto_GitHub/llm-uncertainty-banking/bridge-ui/`. GitHub Actions only runs
   workflows in `<root>/.github/workflows/`.
2. **Commit-first = your only safety net.** Much may be uncommitted. A bad bulk write +
   `git checkout` would restore to a PRE-feature state and lose uncommitted work. **Never
   start a part on an uncommitted pile** — commit a green baseline first.
3. **Truncation guard is real and live.** This repo has a history of partial-write
   truncation (`09_Projeto_GitHub/TRUNCATION_POSTMORTEM.md`). A scanner
   (`09_Projeto_GitHub/scripts/check_truncation.sh`) runs via the pre-commit hook
   (`git config core.hooksPath 09_Projeto_GitHub/.githooks`) and CI. Before committing,
   `git status` must show **renames/edits, never mass deletions**. If a file looks
   truncated, restore with `git checkout HEAD -- <path>`.
4. **Flat layout, dual-import.** `backend/` has **no `__init__.py`**. Modules run flat
   (`uvicorn server:app`) but tests/import-linter run package-mode (`backend.*`). Every
   backend module uses the shim: `try: from X import Y` / `except ImportError: from
   backend.X import Y`. `server.py` also installs a module-attribute proxy
   (`_ProxyingServerModule`) so re-exported, REBOUND scalars (`_AUDIT_SEQ`,
   `_RUNTIME_GUARD_THRESHOLD`, …) stay live across the `server.X` surface. Any new module
   MUST follow the dual-import pattern, or pytest/lint-imports breaks.
5. **Determinism.** This machine may run Ollama. Always gate with
   `BRIDGE_USE_REAL_LLM=off` and `BRIDGE_AUDIT_DB=:memory:` for tests (`verify.sh` already
   exports these).
6. **Windows.** Run Python scripts that print Unicode with `python -X utf8 …` (default
   cp1252 stdout crashes on `→`, `—`, `✓`).

---

## 1. GROUND TRUTH — verified facts + file map

| Fact (VERIFIED) | Location |
|---|---|
| Change store: `submit` / `list` / `decide` exist; **NO apply/deploy** anywhere. `decide_change` only `UPDATE status,reviewer,decided_at,decision_note`. | `backend/routers/governance_changes.py` |
| Schema: `change_requests(id, kind, summary, payload TEXT, submitted_by, submitted_at, status, reviewer, decided_at, decision_note)`. `payload` is **JSON in a TEXT column** → extensible with **no migration**. `status` ∈ {pending, approved, rejected}. Kinds (`_KINDS`): `agent, intent, dq_rule, rag_doc` (else `other`). | same |
| Endpoints: `POST /governance/changes`, `GET /governance/changes`, `POST /governance/changes/{id}/decision`. SoD enforced (`reviewer != submitter`). Decision response carries `sod_enforced` (bool) + `sod_warning` when `BRIDGE_AUTH=off`. | same |
| Auth seam only: `verify_token`, role check (`validator`/`admin`), `BRIDGE_AUTH` flag. **No identity provider / user store / login.** | `backend/routers/auth.py` |
| `apply_guard(confidence, threshold, intent, risk_level)` is a **pure function** — reads NO policy store. | `backend/core/guard.py:37` |
| `_RUNTIME_GUARD_THRESHOLD`, `_RUNTIME_CACHE_ENABLED` are **live, mutable** module scalars: read by the `/query` guard stage every request, **already writable** via `PUT /settings`. | `backend/server.py:337-338` (proxied) + `backend/routers/settings.py:94-96` |
| `_INTENT_CATALOG` is a **`Final[list[dict]]` hard-coded in source**, **no writer**. Read by `routers/{discovery,experiments,audit}.py` + `server.py` calibration. **`classify_intent` does NOT use it** — it classifies via hard-coded marker tuples + `_INTENT_KEYWORDS`. → adding a catalog entry makes it *appear* in /intents+eval but the **classifier will not detect it** without new marker code. | `backend/core/classifier.py:784` (catalog) / `:658` (classifier) |
| No `policy` / `dq_rule` store exists (only the `kind` label). Greenfield. | — |
| Provider registry (`backend_registry`, `register_backend`, `resolve`) exists but is **NOT wired** into `_select_backend()` (its own docstring says so). | `backend/core/providers.py`, `backend/backends.py` |
| Honesty component: Live / Demo / Not configured. | `frontend/components/StateBadge.tsx` |
| Flow strip = **7 boxes** (`STAGES`) — a simplified view of the **12-stage** `/query` pipeline. | `frontend/.../views/Painel.tsx` vs `server.py` |
| Nav rail single source = 10 views. | `frontend/.../console/ConsoleShell.tsx` (`CONSOLE_VIEWS`) |
| Connections view: read-only, "＋ New" disabled, still Portuguese. | `frontend/.../views/Conexoes.tsx` |
| Translation: `python -X utf8 _reorg/translate_ui_to_en.py` → ~343 repl / 41 files, ~364 PT-accented lines remain (manual/dict tail). | `_reorg/translate_ui_to_en.py` |
| One-command gates. | `09_Projeto_GitHub/llm-uncertainty-banking/scripts/verify.sh` |

---

## 2. THE ONE IDEA

Every list runs the same loop a firewall uses:

> **create → configure → stage → approve → deploy → monitor**

`＋ Add` opens one slide-over; **Save stages** (never goes live). Staged changes collect
in a global **Pending Changes** tray. A **different** person approves (SR 11-7).
**Deploy** applies it to the live store. The UI links the result to **Audit**. That loop
IS the product.

---

## 3. GUARDRAILS (non-negotiable)

- **Honesty or "Not configured".** A `＋ Add` is backed by a real apply-path + writable
  store + **live read-site**, or it renders `Not configured` via `StateBadge`. No dead
  forms. No button that pretends.
- **"Deployed" must mean LIVE.** For every kind, name the exact request-path read-site
  that consumes the store. If nothing reads it per request, it is theatre — keep it
  `Not configured` until the read-site lands.
- **Reuse, don't fork.** Extend `change_requests`; do not build a second staging system.
- **Deploy is a demo action until auth (Part E).** Surface the existing
  `sod_enforced: false` + `sod_warning` verbatim; never hide it.
- **Each part ships verified.** FE: `tsc --noEmit` + `next build`. BE: `pytest` for the
  touched router + a new test per `apply_*`. Commit only green + truncation-clean.

---

## 4. KEYSTONE — the staging / apply model (the spine; build surgically)

**4.1 Extend the change record (no schema migration — store inside the `payload` JSON):**

```jsonc
{
  "op": "create" | "update" | "delete",
  "target_id": "policy-42" | null,        // null for create
  "before": { ... } | null,                // snapshot at SUBMIT time (enables diff)
  "after":  { ... } | null                 // desired state (null for delete)
}
```

Add a new terminal status value `applied` (+ `applied_at`, `audit_seq`) written by the
executor. Keep `pending` / `approved` / `rejected` unchanged.

**4.2 Apply/deploy executor — a registry `kind → apply(change)`:**

```python
APPLY = { "policy": apply_policy, "intent": apply_intent,
          "dq_rule": apply_dq, "provider": apply_provider }
```

`apply(change)` MUST: (a) require `status == "approved"` AND a `validator/admin` role
(reuse `verify_token`); (b) **optimistic-concurrency check** — re-read current live state
and reject (409) if it no longer equals `change.before` (prevents stale-snapshot TOCTOU
when two changes touch one target); (c) mutate the live store idempotently; (d) write an
**Audit** entry (this is the Deploy→Monitor link); (e) set `status=applied`, `applied_at`,
`audit_seq`.

**4.3 New endpoint:** `POST /governance/changes/{id}/apply` → returns new live state +
`audit_seq`. Role-gated; returns the same `sod_enforced: false` honesty signal while
`BRIDGE_AUTH=off`.

**4.4 Per-kind cost is the READ-SITE, not just the writer.** A writable store with no
request-path reader is dead. See §5.

---

## 5. PER-KIND TABLE — store + apply + read-site + honesty (intent recategorized)

| Kind | Writable store today? | Live read-site (what makes "deploy" real) | Effort | First? |
|---|---|---|---|---|
| **policy: runtime control** (guard threshold, cache on/off) | **YES** — `_RUNTIME_GUARD_THRESHOLD` / `_RUNTIME_CACHE_ENABLED`, written by `/settings` | **ALREADY LIVE** — `apply_guard` reads the threshold every `/query`; cache lookup reads the toggle | **S** | ✅ **M2 first** |
| dq_rule | NO (greenfield SQLite) | the `dq_input`/data-governance stage must read the store per request (today static) | M–L | M2b |
| provider (instance of a known type) | NO — config-derived, read-only | wire `_select_backend()` → `backend_registry.resolve()`; add config-instance writer | M | M3 |
| intent (catalog entry) | NO — `Final` source list, no writer | `/intents` + experiments + calibration read the catalog — but `classify_intent` does **NOT**; new intents are **not detected** without marker code | M–L | later |
| rag_doc | corpus seeded in-memory; confirm writability | `rag_retrieval` stage | M | later |

**Honesty rule applied:** until a kind has store + `apply_*` + a request-path read-site,
its `＋ Add` stays **Not configured**. **Correction vs old plan:** start M2 with
**policy / runtime-control** (read-site already exists → genuinely live with minimal
backend), **NOT `intent`**, which is a `Final` source list with no writer **and** which
`classify_intent` never reads. For intent, the honest definition of "live" is "appears in
the catalog/eval"; "the classifier detects it" is a separate, code-level task — say so in
the UI, don't imply detection.

---

## 6. BUILD ORDER & MILESTONES

**Prerequisite → A → C → B → D → F → E**

- **M1 — thin slice (ship first):** Prereq + **A** + **C**. Fixes all three felt problems
  (navigation, buried governance list, confusing approval) with near-zero backend risk.
  Deploy is stubbed/demo until M2. **Commit green, then reassess.**
- **M2 — make it real:** **B** + 4.1/4.2/4.3 + the **policy runtime-control** store. First
  true create→stage→approve→deploy→live (threshold change takes effect next `/query` +
  writes Audit). Then add **dq_rule** (M2b).
- **M3 — Connections real:** **D** + provider writer + wire `resolve()`.
- **M4 — Monitoring:** **F** + per-rule hit counters.
- **M5 — Auth:** **E** (human-owned).

Do **NOT** attempt all at once. Each milestone is independently shippable + verifiable.

---

## 7. PARTS — Goal · Files · Endpoints · Honesty · Verify · Done-when

### Prerequisite — land the green base
**Do:** `git config core.hooksPath 09_Projeto_GitHub/.githooks`; `bash .../scripts/verify.sh`;
`python -X utf8 _reorg/translate_ui_to_en.py` → `git diff` review (watch short keys:
não/memória/Decisão/Versão/latência/segurança/médio) → re-run verify → commit per
`bridge-ui/docs/CLOSEOUT_CHECKLIST.md`.
**Done-when:** clean tree, gates green, no Portuguese in the console.

### Part A — Flow strip becomes the nav spine `[frontend only]`
**Files:** `Painel.tsx` (`STAGES`), reuse `ConsoleShell` `onSelect`.
**Do:** each of the 7 boxes links to its config screen (Intent→Intent Catalog,
Guard→Policies, Backend→Connections, Audit→Audit, Response→Observability,
Input/Sanitize→request policy). Unbuilt targets link to a `Not configured` state.
**Verify:** `tsc`+build; extend `e2e/console.spec.ts` with a click-through.
**Done-when:** clicking any stage navigates. Note in UI/code: 7 boxes = simplified view of
the 12-stage backend.

### Part C — Pending Changes tray `[frontend on existing backend]`
**Do:** top-bar `Pending (n)` from `GET /governance/changes` `by_status.pending`; panel
lists each staged change with what/who/when + before→after diff (from 4.1); Approve/Decline
(existing `/decision`), Deploy (new `/apply`, lands in M2). Approve disabled on own
submission → tooltip explaining SoD.
**Honesty:** show `sod_warning` verbatim when `BRIDGE_AUTH=off`.
**Verify:** `pytest test_governance_changes.py` still green; FE `tsc`/build; e2e: submit →
appears → second operator approves.
**Done-when:** a staged change is visible, diffable, approvable from the tray.

### Part B — One Create/Edit pattern + the executor `[frontend + backend]`
**FE:** one `<AddSlideOver>` (fields, validation, toast) reused by every list; Save → `POST
/governance/changes` with the 4.1 payload (stages, never live).
**BE:** executor (4.2) + `POST .../apply` (4.3) + the **policy runtime-control apply first**
(`apply_policy` sets `_RUNTIME_GUARD_THRESHOLD` via the server proxy + writes Audit), then
`dq_rule` store + `dq_input` read-site.
**Honesty:** kind without store+apply+read-site ⇒ `Not configured`.
**Verify:** new `pytest` per `apply_*` (stage→approve→apply→live changed→Audit row→re-apply
is idempotent→stale `before` rejected 409); FE `tsc`/build.
**Done-when:** change the guard threshold end-to-end and the next `/query` reflects it with
an Audit row.

### Part D — Connections = real provider management `[frontend + backend]`
**FE:** enable `＋ Add connection` → pick a **known type** (Ollama/OpenAI/Anthropic) →
endpoint + secret-reference → stages a `provider` change; edit/remove per row.
**BE:** `register_backend` the real backends, wire `_select_backend()` →
`backend_registry.resolve()` (the `core/providers.py` TODO), config-instance writer +
`apply_provider`.
**Honesty:** you add **instances of known types**, not brand-new provider types (that needs
code/a plugin) — UI must say so. Secrets by **reference**, never inline.
**Verify:** `pytest` provider writer + resolve; FE `tsc`/build.
**Done-when:** a new Ollama endpoint staged→approved→deployed shows active in topology.

### Part F — Monitoring closes the loop `[frontend + small backend]`
**FE:** post-Deploy confirmation links to the Audit entry; per policy/connection row a small
"hits / last triggered" stat.
**BE:** per-rule hit counter incremented in the guard/backend stage, exposed on
`routers/metrics.py` / `routers/observability.py`.
**Verify:** `pytest` counter; FE `tsc`/build.
**Done-when:** deploying a policy and triggering it increments its visible hit count.

### Part E — Roles & real auth `[BACKEND — human-owned]`
**Goal:** Analyst (submits, can't approve own) / Validator (approves/deploys) / Admin
(manages users) + a Users & Roles screen.
**State:** seam exists (`verify_token`, roles, `sod_enforced`, `BRIDGE_AUTH`). Work = real
identity provider + users/roles table + login → turn `BRIDGE_AUTH=on` into an enforced
control.
**Human-owned:** security-sensitive access control. The executing LLM builds the Users &
Roles UI only; the auth + who-can-deploy is the developer's.
**Done-when:** Approve/Deploy require a signature-bound role and `sod_enforced: true`.

---

## 8. BACKEND TASKS (corrected sizes)

| # | Task | For | Size | Risk |
|---|---|---|---|---|
| B1 | Extend `payload` with `op/target_id/before/after`; add `applied` status + `applied_at/audit_seq` | C, B | S | low |
| B2 | `apply(change)` registry + `POST …/apply`, role-gated, idempotent, optimistic-concurrency, Audit row | B | M | med (live mutation) |
| B3 | `policy` runtime-control apply (`apply_policy` → `_RUNTIME_*`) — read-site already live | B / M2 | S | low |
| B4 | `dq_rule` store + `dq_input` reads it per request | B | M–L | med |
| B5 | Provider config-instance writer + wire `backend_registry.resolve()` into `_select_backend()` | D | M | med |
| B6 | `intent` store + make /intents+eval read it; separately, marker-code path for detection (flag as not-auto) | later | M–L | med |
| B7 | Per-rule hit counters | F | S | low |
| B8 | Real auth + users/roles + login (`BRIDGE_AUTH=on`) | E | L | **high — security, human-owned** |

---

## 9. VERIFICATION & COMMIT PROTOCOL (run on the real machine)

```bash
# gates (one command; already forces fake backend + :memory:)
bash 09_Projeto_GitHub/llm-uncertainty-banking/scripts/verify.sh          # or --frontend / --backend

# backend-only, deterministic, single router:
cd 09_Projeto_GitHub/llm-uncertainty-banking/bridge-ui/backend
BRIDGE_USE_REAL_LLM=off BRIDGE_AUDIT_DB=:memory: python -m pytest test_governance_changes.py -q

# import-linter (package mode, from bridge-ui/):
cd 09_Projeto_GitHub/llm-uncertainty-banking/bridge-ui
python -c "import sys;from importlinter.cli import lint_imports;sys.exit(lint_imports(config_filename='backend/pyproject.toml'))"

# before EVERY commit:
bash 09_Projeto_GitHub/scripts/check_truncation.sh --threshold 5          # exit 0
git status                                                                 # renames/edits, NO mass deletions
```

Commit in small slices; never commit a red or truncation-flagged state. New backend
modules: use the dual-import shim; if a re-exported scalar is rebound at runtime, register
it in `server.py`'s proxy (`_PROXIED_ATTRS`) or routers reading `server.X` get a stale
value.

---

## 10. ACCEPTANCE CRITERIA

- **M1:** every Flow stage navigates; staged change shows what/who/when+diff in the tray; a
  second operator approves; `tsc`/build/`pytest` green; no Portuguese.
- **M2:** stage→approve→deploy a guard-threshold policy → next `/query` reflects it + an
  Audit row exists; apply is idempotent and rejects a stale `before` (409).
- **M3:** add a provider instance the same way; appears active in topology.
- **M4:** a deployed policy shows a live, incrementing hit count.
- **M5:** Approve/Deploy require a signature-bound role; `sod_enforced: true`.

---

## 11. OPEN DECISIONS (human)

- Dormant release/docs/nightly workflows: relocate to root w/ rewritten paths, or split the
  project into its own repo (recommended).
- `Dockerfile`: replace `pip install lub` with a local wheel (supply-chain).
- i18n: English-only now vs a real i18n layer later.

---

## 12. ONE LINE

One loop everywhere: Flow strip becomes the menu (A); a global Pending tray replaces the
buried governance list (C); every list gets the same `＋ Add → stage` form backed by a real
apply executor whose **FIRST live kind is the guard-threshold policy** (read-site already
live), not intent (B); Connections becomes real provider management on the registry (D);
monitoring closes the loop (F); auth/roles (E) is the one human-owned, security piece.
**Build thin first — A + C on a green commit.**
