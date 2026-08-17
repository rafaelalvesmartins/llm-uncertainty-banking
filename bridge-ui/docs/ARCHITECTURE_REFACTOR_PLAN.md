# Architecture Refactor Plan — bridge-ui/backend

> **Date:** 2026-06-15 · **For:** execution on your machine / a terminal-LLM (where
> `import-linter` + the 292 tests run). **NOT** to be run blind in a sandbox without tests.
>
> **Why always gated:** the dual-import already caused a real module-identity bug in the
> audit chain (two instances of `state.audit` with diverging `_AUDIT_SEQ`). In a
> tamper-evident system, every slice of this refactor MUST pass `import-linter` (3/0) +
> `pytest` (292) **before** committing. No gate, no change.

## Target (the 2 P1 debts)

| # | Debt | Today | Target |
|---|---|---|---|
| 1 | **Dual-import** | ~43 files with `try: from backend.X … except ImportError: from X …` | **one mode: package** (`from backend.X` everywhere) |
| 2 | **Huge `server.py`** | 2007 lines (composition root + orchestration + helpers) | ≤ ~400 lines (wiring only); the rest extracted |

The **folder** organization (workspace) is a separate P2 debt — scripts already exist
(`_reorg/reorg_fatia{1,2,3}.{sh,ps1}`); run those separately.

---

## Debt 1 — Kill the dual-import (converge to package mode)

**Why package mode (not flat):** `import-linter` (the architecture guard) uses
`root_packages=["backend"]` — it only works in package mode. `backend/__init__.py` already exists.
So the path that keeps the guard alive is standardizing **everything** on `from backend.X`.

### What changes (coordinated — that's why it needs a gate)
1. **The ~43 files:** remove the `try/except ImportError` block, keep only the
   `from backend.X import Y` form. (Codemod below does the bulk; review by hand.)
2. **App launch:** `uvicorn backend.server:app` running from `bridge-ui/` (not
   `uvicorn server:app` from `backend/`). Update: `start-demo.sh`, `Dockerfile`,
   `scripts/verify.{sh,ps1}` (the pytest step), and any "how to run" doc.
3. **pytest:** run from `bridge-ui/` (so `backend` resolves as a package), or pin
   `pythonpath` in `pyproject.toml [tool.pytest.ini_options]`.
4. **import-linter:** already package mode — no change; it becomes the gate.

### Codemod (draft — run it, then review the diff)
```bash
# from bridge-ui/backend, converts the dual-import into a single package-mode import.
# REVIEW the git diff before trusting — some 'except ImportError' blocks are OPTIONAL-DEP
# guards (e.g. prometheus in server.py), NOT the dual-import; preserve those.
python "$ROOT/_reorg/refactor_dual_import.py" bridge-ui/backend
```
> ⚠️ The codemod is a starting point, not magic. Blocks vary; expect to review the ones it
> doesn't match by hand. Do NOT touch the `try/except ImportError` that guard optional
> dependencies (prometheus-client, etc.) — those must stay.

### Gate for this debt (mandatory, per slice)
```
cd bridge-ui && python -c "import sys;from importlinter.cli import lint_imports;sys.exit(lint_imports(config_filename='backend/pyproject.toml'))"   # 3 kept / 0 broken
cd backend && pytest -q                       # 292 passed
pytest -q test_audit_concurrency.py test_audit_disk_integrity.py  # the bug's regression — MUST pass
uvicorn backend.server:app --port 8000        # boots? /health responds?
```
Slice by cluster (routers first, then state/core), gate + commit each.

---

## Debt 2 — Slim `server.py` (2007 → ~400)

`server.py` still holds more than wiring. Extract, **one thing per slice**:

| Leaves server.py | Goes to | Gate |
|---|---|---|
| Endpoint handlers not yet turned into routers | `routers/<new>.py` (pattern exists; 22 routers already) | import-linter + pytest |
| The 12-stage pipeline orchestration | `core/pipeline.py` (the `core` layer) | import-linter (core doesn't import server) + pytest |
| Inline helpers/utilities | `core/` or `state/` per the layer | import-linter + pytest |
| The `_ProxyingServerModule` (lines ~2016+) | keep (it's the decoupling mechanism) | — |

Goal: `server.py` = create the `app`, mount routers, register the proxy. No logic.
Each extraction is a slice: move → `import-linter` (no new cycle) → `pytest` → commit.

---

## Recommended order & execution

1. **Debt 1 first** (dual-import) — it's the one that already caused a bug and a sanity
   prerequisite for touching server.py. Codemod → review diff → gate → commit per cluster.
2. **Debt 2** (slim server.py) — small extractions, gate each.
3. **Folder reorg** (P2) — run the ready scripts whenever; cosmetic, no urgency.

**The loop that works:** you (or the terminal-LLM) run a slice → run the gates → paste me the
output (including the truncation false-EOF gotcha) → I fix the code → you re-verify → commit.
I design the precision; the gate runs where the tests live.

## What stays intact
The honesty layer, the audit chain (logic), the unified frontend, the scale adapters, and the
`import-linter` contract (which becomes the judge of this very refactor).

### One-line summary
Converge the dual-import to package mode (kills the audit-bug class) and empty `server.py` down
to wiring only — in slices, each gated by `import-linter` 3/0 + `pytest` 292, executed where the
tests run. Folders: scripts ready, just run them.
