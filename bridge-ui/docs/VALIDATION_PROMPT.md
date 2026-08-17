# Validation Task — Bridge Console (bridge-ui): what actually works, what doesn't

> Paste everything below the line into your terminal LLM (Claude Code or similar) running
> on the real Windows machine. It is self-contained and assumes no prior conversation.

---

You are validating an existing codebase on THIS machine (Windows, real intact files,
Python 3.11+, full shell + file access). Your job: determine **with evidence** what is
actually working and what is not, and explain it.

**This is READ-ONLY validation.** Run gates and smoke tests; report truthfully. Do **NOT**
fix, refactor, translate, `git add`, `git commit`, `git checkout`, or `git reset` — the
working tree has ~330 uncommitted files and a destructive git op would lose work. Never
claim a gate passed without running it and seeing the exit code. If you can't run
something, say so explicitly — do not infer or fake a result.

## 0. Context
- Monorepo. Git root: `c:\code\eb2niw`. Branch: `product/bridge-platform`.
- App: `09_Projeto_GitHub\llm-uncertainty-banking\bridge-ui\` — `frontend/` (Next.js 14,
  App Router, BFF proxy under `app/api/*`) + `backend/` (FastAPI, 12-stage `/query`
  pipeline, tamper-evident audit hash-chain, governance with submitter≠approver / SR 11-7).
- Working tree is UNCOMMITTED. Do not commit or stage anything.

## 1. Hazards (respect these or you corrupt the repo / produce false results)
1. **Python 3.11+ required** (`from datetime import UTC`). Run `python --version` first; if
   < 3.11, report it and SKIP the backend gates (don't fake them).
2. Backend is **flat-layout, no `__init__.py`**; tests/lint run package-mode via the exact
   commands below. Modules use a `try/except` dual-import shim and `server.py` installs a
   module-attribute proxy — don't "fix" these.
3. **Determinism:** export `BRIDGE_USE_REAL_LLM=off`, `BRIDGE_AUDIT_DB=:memory:`,
   `BRIDGE_CHANGES_DB=:memory:` before pytest, or it may hit a live Ollama and flake.
4. **Windows Unicode:** run any Python script that prints `→ — ✓` with `python -X utf8`.
5. If `npm run dev`/`build` throws `Cannot find module './XXXX.js'`, that's a **stale
   `.next` cache**, not a code defect: `Remove-Item -Recurse -Force .next` then retry, and
   note it as cache.

## 2. Gates — run each, record exit code + the last ~15 lines of output

### Frontend — `...\bridge-ui\frontend`
```
npm run lint
npx tsc --noEmit
npm run build
npx playwright test e2e/polish.spec.ts e2e/tabs.spec.ts e2e/console.spec.ts
```

### Backend — `...\bridge-ui\backend`
```
$env:BRIDGE_USE_REAL_LLM="off"; $env:BRIDGE_AUDIT_DB=":memory:"; $env:BRIDGE_CHANGES_DB=":memory:"
python -m pytest -q
ruff check .
mypy .
```

### import-linter (the architecture contract) — `...\bridge-ui`
```
python -c "import sys;from importlinter.cli import lint_imports;sys.exit(lint_imports(config_filename='backend/pyproject.toml'))"
```

### One-command alternative (does all of the above)
```
.\09_Projeto_GitHub\llm-uncertainty-banking\scripts\verify.ps1
```
(or, under git-bash/WSL: `bash 09_Projeto_GitHub/llm-uncertainty-banking/scripts/verify.sh`)

### Integrity — `c:\code\eb2niw`
```
bash 09_Projeto_GitHub/scripts/check_truncation.sh --threshold 5
```

**Claimed baselines — verify, do not assume:** pytest ≈292 passed / ≈16 skipped · tsc
clean · next build clean · lint-imports 3 contracts kept / 0 broken · ruff clean · mypy
clean (~39 files) · truncation clean.

## 3. Runtime smoke — does it actually run end-to-end?
```
# Terminal 1 — backend
cd ...\bridge-ui\backend
$env:BRIDGE_USE_REAL_LLM="off"; uvicorn server:app --port 8000
# Terminal 2 — frontend
cd ...\bridge-ui\frontend
npm run dev
```
Then confirm (report result + evidence for each):
- `GET http://localhost:8000/health` → ok.
- `GET http://localhost:3000/api/integrations` (frontend BFF) → returns a provider list.
- `POST http://localhost:8000/query` body `{"query":"Show my account balance","channel":"app","customer_id":"demo"}` → returns a decision + stage trace.
- Open `http://localhost:3002/` and load **all 8 console views**: Dashboard, Flow,
  Connections, Policies, Audit, Observability, Governance, Config. Note
  any view that errors, is blank, or shows a "backend offline" state.
- Confirm the legacy deep-link redirects still work: `/console#metrics` lands on the
  Dashboard and `/console#sessions` lands on Audit's "By customer" view.
- Governance: `GET /api/governance/changes` lists; submit a change, then approve it as a
  DIFFERENT operator and confirm the SR 11-7 segregation-of-duties block fires when you try
  to approve your own.

## 4. Claims to confirm — mark each CONFIRMED / REFUTED / CAN'T-TELL with file:line or output
1. The governed-change loop has submit/approve/list but **no deploy**: no `/apply`
   endpoint, no `apply()` executor anywhere. (`backend/routers/governance_changes.py`)
2. `_select_backend()` probes Ollama hard-coded and **ignores** `backend_registry`.
   (`backend/backends.py`)
3. Guard threshold is live-mutable, read every `/query`, written by `PUT /settings`:
   `_RUNTIME_GUARD_THRESHOLD` (`server.py:337`, `settings.py:94`).
4. `_INTENT_CATALOG` is `Final` with no writer, and `classify_intent` doesn't read it.
   (`core/classifier.py`)
5. DQ rules are hard-coded defaults (`_DQ_INPUT/_DQ_OUTPUT`, `server.py:343-344`); RAG is
   `InMemoryDocumentStore` (`server.py:410`) — no persistence.
6. Auth is a seam only: EdDSA JWT + ephemeral demo key + `POST /auth/token` +
   `verify_token`, gated by `BRIDGE_AUTH` (off by default). Grep the **frontend** —
   confirm it never calls `/auth/token`, so the role check is currently unreachable.
   (`backend/routers/auth.py`)
7. Translation is incomplete: ~370 accented (Portuguese) lines remain across ~39 frontend
   `.ts/.tsx` files. (rough check: `rg -c "[áàâãéêíóôõúüç]" frontend`)
8. CI: 5 dormant workflow YAMLs under
   `09_Projeto_GitHub\llm-uncertainty-banking\.github\workflows\` (GitHub only scans
   `<root>\.github\`); active copies live at `eb2niw\.github\workflows\`.

## 5. Output — produce one structured report
- **Verdict (1 short paragraph):** Is the app green and runnable today? What is the single
  biggest gap?
- **Gate results table:** gate · command · exit code · pass/fail · key output line.
- **Runtime smoke table:** check · result · evidence.
- **Claims table:** # · confirmed/refuted/can't-tell · file:line or output snippet.
- **Three lists:** WORKING (green + runs) · PARTIAL (runs but incomplete) · NOT BUILT
  (claimed-missing, confirmed absent).
- **Surprises:** anything that is a *real defect* (vs. known-incomplete). Separate "broken"
  from "not built yet."

Ground every line in actual command output. Do not change any file. When done, give the
report only — no fixes, no commits.
