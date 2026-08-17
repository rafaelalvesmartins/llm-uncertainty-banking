# Closeout Checklist — run on your machine (git root = eb2niw)

> Order by design: **lock in the verified wins first, leave the risky bit for last.**
> Everything on your machine (the sandbox can't run tests or git safely).
> Where it says "→ paste to Claude", send me the output and I'll close it out.

---

## Step 0 — Setup (once)
```
# deps
cd 09_Projeto_GitHub/llm-uncertainty-banking
pip install -e ".[dev]" ; pip install -r bridge-ui/backend/requirements.txt
( cd bridge-ui/frontend && npm ci )

# enable the truncation guard BEFORE any commit (it was dead; I fixed the path)
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath 09_Projeto_GitHub/.githooks
```

## Step 1 — Baseline: confirm everything is green NOW
```
bash 09_Projeto_GitHub/llm-uncertainty-banking/scripts/verify.sh     # or verify.ps1
```
Expected: frontend `tsc`/`build`/`lint` + backend `ruff`/`mypy`/`lint-imports`/`pytest` (~292) green.
- ❌ If anything breaks → **paste the output to Claude** (watch the truncation false-EOF). Don't proceed until green.
- ✅ Green → proceed.

## Step 2 — Commit the UNIFICATION (the already-verified win — lock it first)
```
bash _reorg/commit_unification.sh        # or .ps1 — runs the guard + stages + shows status
git status --short                       # CHECK: A/M/R, NO mass deletions
# if the status looks right, run the commit the script printed
```

## Step 3 — Architecture refactor (the risky one — auto-reverts; a loop with me)
```
bash _reorg/run_refactor.sh
```
- It applies the codemod (dual-import → package mode) → runs `import-linter` + `pytest` →
  **if anything breaks, it `git checkout`s and reverts itself.** Safe to try.
- The first run will probably revert (stray flat imports) → **paste the first error to Claude**.
- I fix it, you run again. 2–3 rounds to green.
- ✅ Green → update the launch to package mode (`uvicorn backend.server:app` running from
  `bridge-ui/`; adjust `start-demo.sh`, `Dockerfile`, `scripts/verify`) → commit the slice.
- (Then, optional: slice `server.py` — same logic, gate per extraction. See
  `ARCHITECTURE_REFACTOR_PLAN.md`.)

## Step 4 — Organize folders (cosmetic, low risk)
```
bash _reorg/reorg_fatia1.sh              # review the dry-run (10 moves)
bash _reorg/reorg_fatia1.sh --execute
bash 09_Projeto_GitHub/scripts/check_truncation.sh --threshold 5
git status                               # renames (R), no stray deletions
git commit -m "chore(org): slice 1 — loose docs -> docs/<theme>"
#   repeat slice2 (18 moves) and slice3 (25, NIW — item by item, PDFs by hand)
```

## Step 5 — Push + confirm CI (it was dormant; I relocated it to the root)
```
git push
# open GitHub Actions: bridge-ui.yml + ci.yml + truncation-check.yml should TRIGGER.
# (the first run may fail on --cov-fail-under=80 — expected; adjust the baseline later.)
# DELETE the nested copies that never trigger:
git rm 09_Projeto_GitHub/llm-uncertainty-banking/.github/workflows/bridge-ui.yml
git rm 09_Projeto_GitHub/llm-uncertainty-banking/.github/workflows/ci.yml
git commit -m "ci: remove dormant nested workflows (root copies are active)"
```

---

## Your decisions (not automated — external effects / product)
- **release.yml / docs.yml / nightly-calibration.yml** are still dormant (publish/deploy/cron).
  Decide: relocate carefully **or** extract `llm-uncertainty-banking` into its own repo
  (recommended — the whole CI comes back without mixing with the petition workspace).
- **Dockerfile**: replace `pip install lub` with a local wheel/path (supply-chain).
- **Scale (Track D)**: only when the goal becomes millions/day (measure with the load-test first).

## Verification state (what's proven vs. what these steps close)
| Already verified | These steps close |
|---|---|
| Unification: tsc/build/--list (me) + runtime 6/6 (browser) + 292/27 (other terminal) | Its commit (P2), the architecture refactor (P3), the reorg (P4), live CI (P5) |

### Summary
Setup → green baseline → **commit the unification** → **refactor (loop with me)** → reorg → push/CI.
The "paste to Claude" points are where I step in to fix code with the real gate behind it.
