# VERIFICATION_HANDOFF — bridge-ui (updated 2026-06-15)

> **Two audiences, two parts.** **Part A** (visual, in the browser) can be done by a
> browser assistant (no terminal). **Part B** (gates) needs a terminal — you or a
> shell-capable LLM. Don't mix them: nobody should report PASS/FAIL for something they
> didn't actually run.

---

## ⚠️ Read first — truncation hazard (this repo has a history of it)

Edited files sometimes appear **truncated** (cut off at the end) and produce FALSE
syntax/EOF errors. Before "fixing" an error that sits at the END of a file, open it and
confirm it closes properly. Before committing anything:

```
bash 09_Projeto_GitHub/scripts/check_truncation.sh --threshold 5   # or the .ps1
```

---

## PART A — Visual checks (browser) ✅ can be a browser assistant

### Pre-conditions (CRITICAL — skipping these causes false FAILs)

1. **RESTART `npm run dev`.** `next.config.js` was changed (rewrite `/` → `/console`) and
   Next only picks that up on restart. `Ctrl+C` in the dev terminal → `npm run dev` again.
   Without it, the root `/` won't switch and check (a) fails by mistake.

2. **Backend on `:8000` is optional — and its absence is NOT a failure.** The 4 new groups
   host panels that fetch from the backend. Without it running, they **render but show an
   error/loading state**. Distinguish:
   - ✅ panel **renders** + shows "backend offline / loading" → **structurally OK**
   - ❌ panel **disappears** / blank screen / **red error in the console (F12)** → **real problem**

   (To see the panels WITH data: `cd bridge-ui/backend && uvicorn server:app --port 8000`
   in another terminal — but that needs the Python env with `lub` installed.)

### Checks — open `http://localhost:3002/` (the ROOT, not `/console`)

- **(a)** The root `/` shows the **console** (left rail), not the legacy app.
- **(b)** The rail has **10 items**: Painel · Fluxo · Conexões · Políticas · Auditoria ·
  Métricas · Sessões · Observ. · Governança · Config.
- **(c)** Clicking the **4 new groups**, the legacy panels appear (with data if the backend
  is up; otherwise an error state = OK):
  - **Sessões** → Sessions, Assistant, Playground
  - **Observ.** → Metrics, Drift, Ops, Fleet, ModelCard, Calibration, Vulnerability, Experiments
  - **Governança** → Compliance, Regulatory, Evidence, GovernedChanges, Visibility, Intents
  - **Config** → Controls, Integrations, InfoPanels, HowThisWorks
- **(d)** The 6 original views (Painel/Fluxo/Conexões/Políticas/Auditoria/Métricas) still work.
- **(e)** Browser console (F12) has **no red app errors** ("backend offline" warnings from a
  failed fetch are OK; React/render errors are NOT).
- **(f)** `http://localhost:3002/console` shows the **same** content (the direct route still works).

**Report:** which of (a)–(f) passed, and the list of panels showing a **real render error /
blank screen / infinite spinner** (vs. those that only show "backend offline", which is OK).

---

## PART B — Terminal gates ⛔ needs a shell (you or a shell-capable LLM)

### Setup (once)
```
cd 09_Projeto_GitHub/llm-uncertainty-banking
pip install -e ".[dev]" ; pip install -r bridge-ui/backend/requirements.txt
( cd bridge-ui/frontend && npm ci )
```

### Gates (one command)
```
# Windows:
.\09_Projeto_GitHub\llm-uncertainty-banking\scripts\verify.ps1
# bash/WSL:
bash 09_Projeto_GitHub/llm-uncertainty-banking/scripts/verify.sh
```
Expected: frontend `lint`/`tsc`/`build` green; backend `ruff`/`mypy`/`lint-imports`/`pytest`;
truncation guard. Baselines (other terminal): pytest **292 / 16 skip**, mypy ~38,
lint-imports **3 contracts / 0 broken**.

### e2e — EXPECTED TO BREAK on the old specs unless repointed
The legacy specs now target `/legacy` (the legacy app, preserved); `console.spec.ts` targets `/`.
```
cd bridge-ui/frontend ; npx playwright test
```

---

## Report format
- **Part A:** (a)–(f) PASS/FAIL + the list of panels with a real render error.
- **Part B:** per gate, PASS/FAIL + the first error (file:line).
- **Do not commit** until reviewed. Run `check_truncation` before any commit.

> Honest note: the build already passes in CI/sandbox, but "build green ≠ render green" —
> Part A is the only thing that proves each hosted panel actually renders. And the visual is a
> **mix** (new shell + legacy-styled panels) — coherent, because the legacy `globals.css` and
> the `bc-*` tokens share the same palette.
