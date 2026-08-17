# Consolidated Prioritized Analysis — bridge-ui / llm-uncertainty-banking

> **Date:** 2026-06-15 · **For:** review + MR attachment.
> **State:** nothing committed (tree: ~27 modified + ~12 new, no deletions).
>
> **Scope — and what this is NOT:** this analysis covers the `eb2niw` monorepo
> (code in `09_Projeto_GitHub/llm-uncertainty-banking`, demo app in `bridge-ui`).
> **None** of the auth/OTP/Prisma/IDOR/Sonar report from another project applies
> here — there is no `auth.ts`, `middleware.ts`, OTP, or Prisma in this code.
>
> **Severity:** P0 = blocks the goal · P1 = important, not blocking · P2 = improvement.
> **Owners:** `[here]` sandbox without torch · `[term+torch]` terminal with the ML
> suite · `[machine]` dev machine (native git) · `[platform]` infra team.

---

## 1. Validated state (solid)

| Item | Evidence | Status |
|---|---|---|
| Frontend type-check (strict) | `tsc --noEmit` = 0 errors (re-run, incl. Painel edits) | ✅ |
| Frontend production build | `next build` exit 0, `/console` 15.2 kB | ✅ |
| Backend scale adapters | `pytest scale/` = 39 passed, 5 skipped (real) | ✅ |
| Honesty layer (6 views) | dedicated review: every `StateBadge` valid, statuses honest | ✅ |
| Truncation guard | path fixed (scanner in `scripts/`); 0 wrong refs; hook intact | ✅ |
| CI relocated (test workflows) | `bridge-ui.yml` + `ci.yml` at root, monorepo paths, **no publish** | ✅ |
| Painel (reported glitch) | svg `bc-topo` (no clip) + "＋ Nova" pill + real-data summary | ✅ |
| `verify.sh` determinism | env `BRIDGE_USE_REAL_LLM=off` + audit `:memory:` (override-safe) | ✅ |

> **Taken on trust (not reproducible here — torch doesn't fit a 4 GB sandbox):**
> full `pytest 292 / 16 skip`, `e2e 27/27`, `mypy 38 files`,
> `lint-imports 3 contracts / 0 broken`, `bandit 0 high` — run by the other terminal.

---

## 2. P0 — Blockers (prioritized)

### P0.1 — Architecture is not stateless / single-node `[platform]` `[term+torch]`
In-memory state (`_AUDIT`, `_METRICS`, `_CACHE`, rate-limiter), SQLite for audit, and
`_OLLAMA_SEMAPHORE(1)` = 1 inference at a time. **Won't handle millions/day.**
- **Blocks:** prod *at scale*. **Does NOT block** the single-node pilot.
- **Fix:** Track D (weeks) — externalize state (Postgres/Redis), async I/O, an LLM serving
  tier. The adapters already exist behind a flag (`scale/`), not wired.
- **Before trusting it:** run `loadtest/query_load.js` for the real single-node ceiling.

### P0.2 — Dockerfile installs the wrong `lub` (supply-chain) `[platform]`
`pip install lub` pulls a **squatted** PyPI package; the real dist is `llm-uncertainty-banking`.
- **Fix:** install via a local wheel / path (`-e ./...`), never `pip install lub`.

### P0.3 — Dormant workflows with EXTERNAL effects `[machine]` (decision)
`release.yml`, `docs.yml`, `nightly-calibration.yml` are still nested (never trigger).
Relocating them to the root = **activating publish/deploy/cron inside the NIW petition repo**.
- **Decision needed:** (a) relocate with rewritten paths *and* review every external effect,
  OR (b) **extract `llm-uncertainty-banking` into its own repo** — then the original paths
  already work and the whole CI comes back without mixing with the personal workspace.
  **Recommend (b).**

---

## 3. Test gaps

| Gap | Sev | Owner |
|---|---|---|
| Full suite (292) only runs with the ML stack (torch) | P1 | `[term+torch]` / CI |
| Adapter integration (real Redis/Postgres) not exercised | P1 | `[term+torch]` |
| `audit_postgres`: cross-store parity (SQLite↔PG) + advisory lock before trusting | P1 | `[term+torch]` |
| Redis limiter: fixed-window vs token-bucket divergence (documented in SCALE_WIRING) | P2 | `[here]` doc ✓ |
| Revived `ci.yml` may fail `--cov-fail-under=80` on first push | P2 | `[machine]` |

---

## 4. Process gaps

| Gap | Sev | Action | Owner |
|---|---|---|---|
| Nothing committed (~39-file blob) | P1 | slice + commit (step → verify → commit) | `[machine]` |
| Folder reorg pending (3 slices, scripts ready) | P2 | run `reorg_fatia{1,2,3}.sh` | `[machine]` |
| Truncation guard fixed but not installed | P1 | `git config core.hooksPath 09_Projeto_GitHub/.githooks` | `[machine]` |
| CI never confirmed on a real push | P1 | push and watch Actions | `[machine]` |
| **Dual-import bug class** (`backend.` vs flat) — the real audit trap | P1 | converge to one import mode | `[term+torch]` |

---

## 5. Tech debt / improvements (P2)

- **Kill the dual-import:** standardize on `uvicorn backend.server:app` + always `from backend.`;
  remove the flat fallbacks. Eliminates the "two instances of the same module" class — dangerous
  in a tamper-evident chain.
- **Coverage ratchet:** with pytest at 292 green, pin `--cov-fail-under` to the real baseline and
  raise it; drop the `|| true` on `pip-audit` once deps are pinned.
- **`verify.sh` as the single gate** + the pre-commit truncation hook = a cheap verification loop.
- **e2e in CI** starts the backend (`uvicorn`) in the job and drops `continue-on-error`.

---

## 6. Who-does-what matrix

| Owner | Items |
|---|---|
| **`[here]`** (me, orthogonal, no torch) | this analysis · the `.ps1` scripts · docs (SCALE_WIRING, NEXT_STEPS) · static reviews |
| **`[term+torch]`** | run the full suite · audit cross-store parity · kill the dual-import |
| **`[machine]`** (dev) | commit in slices · push (confirms CI) · reorg `--execute` · install the hook |
| **`[platform]`** | secret/KMS · Postgres + Redis · LLM serving tier (Track D) · Dockerfile/wheel |

---

## 7. Recommended sequence

1. **Install the guard** (`core.hooksPath`) + run `scripts/verify.sh` → green local baseline.
2. **Commit the already-done hardening in slices** (it's an uncommitted blob today).
3. **Decide P0.3** — extract `llm-uncertainty-banking` into its own repo (recommended) vs relocate.
4. **Push** → confirm CI triggers and goes green (the Dockerfile P0.2 lands here).
5. **Reorg** the folders (slices 1→2→3) — cosmetic, do it after what matters.
6. **Track D** (P0.1) — only when the goal becomes scale; measure with the load-test first.

---

## 8. Platform / team items (not automatable by me)

- **Secret manager / KMS** for credentials (there's a hardcoded-demo TODO in `auth.py`).
- **Durable Postgres** (audit) + **Redis** (cache/rate-limit/idempotency) provisioned.
- **LLM serving tier** (vLLM/TGI multi-GPU or a managed API) — removes the semaphore=1.
- **Dockerfile:** build with a local `lub` wheel; musl image smoke-tested.
- **Observability:** Prometheus already has the guarded endpoint (`/metrics/prometheus`) +
  `prometheus.yml` pointed at it; still need to stand up the stack + Grafana.

---

### One-line summary
The verifiable hardening is green; what's missing for prod isn't the runtime code — it's 3 P0s
(stateless/scale, Dockerfile/lub, workflows with external effects) + committing + confirming CI on
a push. Nothing from the auth/OTP/Prisma report applies to this project.
