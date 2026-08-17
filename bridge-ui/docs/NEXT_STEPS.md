# Bridge UI — status & next-steps plan (organized)

> One place that ties the whole session together: what's done, what needs verifying,
> and what to do next **in order**. Honest status — most code changes this session were
> made without a runtime (no `tsc`/`dev`/`pytest` here; VM down; git mount corrupted), so
> almost everything is "built, not yet verified." Verification gates everything else.

## TL;DR — do these 3 first

1. **Verify** — run `docs/VERIFICATION_HANDOFF.md` (start: `cd bridge-ui/frontend && npx tsc --noEmit`). Fix what it reports.
2. **Commit** the verified work locally (scoped — see Phase 1).
3. **Decide** how far to take the unify (slices 2–4) and whether to start the scale wiring.

---

## Where we are (status)

| # | Area | What was done | Status | Next |
|---|---|---|---|---|
| A | `/console` redesign (firewall) | foundation (shell/tokens/contract) + 6 views + Painel overview (cards+flow+topology+events) | ⚠️ built, unverified | `tsc` + open `/console` |
| B | Unify slice 1 — rail on `/` | wrapped `page.tsx` into rail; rail CSS in `globals.css` (e2e-safe: roles/ids kept) | ⚠️ built, structure checked by hand | `tsc` + `e2e` + open `/` |
| C | Review fixes | R1/R2/R3 were already fixed in repo; applied: Politicas badge, dead-code, unmount guards, Fluxo cancel-abort, css 11px, `+cryptography` | ⚠️ built, unverified | `tsc` + `pytest` |
| D | Hardening | CI workflow, import-linter `pyproject`, pre-commit, `test_ollama_resilience.py`, `.env.example`, `.gitignore`, docs→`docs/` | ⚠️ needs first CI run | `lint-imports` (likely needs a tweak) |
| E | Scale layer (Track D) | Redis cache/limiter, Postgres audit, Prometheus exporter, deploy infra, `SCALE_WIRING.md` — all additive/inert/flag-gated | ⚠️ scaffolding, unvalidated | `pytest scale/` + real Redis/PG |
| F | Plans & docs | `ENGINEERING_HARDENING_PLAN.md` (+Track D), `ARCHITECTURE_REVIEW.md`, `VERIFICATION_HANDOFF.md`, `SCALE_WIRING.md`, this file | ✅ done | — |

**Blockers I can't clear from here:** no runtime to verify; the sandbox git was corrupted, so the **commit must be done on your machine**.

---

## The plan (ordered phases)

Each step says **who** runs it and **how to verify**. Don't start a phase before the previous one is green.

### Phase 0 — Verify the current work *(you run; I fix)*
- Run `docs/VERIFICATION_HANDOFF.md` top to bottom. Verify: `tsc` clean, `build` ok, `e2e` 27 pass, `pytest` green, `lint-imports` passes.
- Likely fixes: type errors in the new views; `import-linter` `ignore_imports`. **Paste errors → I fix.**

### Phase 1 — Commit *(you run, locally)*
```
cd …/llm-uncertainty-banking
git add bridge-ui .github/workflows/bridge-ui.yml
git status   # confirm adds/modifies/renames — NOT mass deletions
git commit -m "feat(console): firewall /console + rail on / + hardening + scale scaffolding"
```

### Phase 2 — Finish the unify (one app) *(I build in slices; you verify each)*
- **2a** restyle `globals.css` to the new tokens → repaints all legacy panels at once (e2e-safe: keep class names).
- **2b** fold the console's Painel/Fluxo/Conexões into `/` as rail sections.
- **2c** retire `/console` (redirect → `/`) so there's truly one app.
- **2d** update `e2e/` for the rail; run locally.

### Phase 3 — Make hardening enforceable *(I fix + you enable)*
- Fix the `import-linter` contract until `lint-imports` is green.
- Enable the CI workflow on PRs; generate `.secrets.baseline`; commit `frontend/package-lock.json`.
- Verify: a seeded regression (e.g. `import server` in `core/`) fails CI.

### Phase 4 — Measure scale *(you run)*
- `loadtest/query_load.js` (k6) against the single node → baseline p95/p99 + where 429s start. This justifies/prioritizes Phase 5.

### Phase 5 — Scale wiring (Track D) *(I build per slice; you validate with real services)*
- Order from `docs/SCALE_WIRING.md`: Redis cache → limiter → **Postgres audit (parity gate first)** → `/metrics` → multi-worker/LB → LLM serving tier → autoscale.

### Phase 6 — Production trust substrate *(per `PRODUCT_PLAN_V6.md`)*
- auth → RBAC → multi-tenant isolation → KMS/TSA. **Auth must not ship before tenancy.**

---

## Also worth doing (lower-priority polish backlog)

- Document the `/api/metrics` BFF bundle shape in `components/console/types.ts` (Painel + Metricas both depend on it implicitly).
- Extract a typed BFF client layer (`lib/api/*`) so views stop hand-rolling `fetch`.
- Converge legacy panels onto the `bc-*` design tokens (part of Phase 2a).
- a11y: `<caption>`/`aria-label` on the dashboard tables; confirm the 11px floor everywhere.
- Vertical-rail arrow-key polish is done; confirm `tabs.spec.ts` still green after Phase 2.

## What I can do next without a runtime (just say which)
- Deeper **static review** of the rewritten views (closest to a hand-run `tsc`).
- Draft **Phase 2a** (the `globals.css` token restyle) for you to paste + reload.
- Draft the **Phase 5 step-1 wiring** (exact `server.py` lines to swap `_CACHE` → `get_cache(...)` behind `REDIS_URL`).
