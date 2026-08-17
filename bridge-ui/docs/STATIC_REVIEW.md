# Static review of the session's frontend (hand-run "tsc") + 2 drafts

> **Method + caveat:** this is a *read-level* type/JSX review of every file changed this
> session — the closest thing to `tsc --noEmit` I can do without a runtime. It is NOT a
> substitute for actually running `tsc`/`eslint`/`next build` (still the gate, per
> `VERIFICATION_HANDOFF.md`). Good news: I found **no blocking type/JSX error**; one
> defensive fix already applied; the rest is non-blocking.

## Per-file verdict

| File | Verdict | Note |
|---|---|---|
| `app/page.tsx` | ✅ clean | rail wrap balanced (`shell-row`→`tabbar.rail`+`shell-main`→sections); `onTabKey` fwd/back typed ok; roles/ids preserved |
| `app/console/page.tsx`, `layout.tsx` | ✅ clean | hash router + provider inheritance ok |
| `components/console/ConsoleShell.tsx` | ✅ clean | imports React; `CONSOLE_VIEWS`/props typed |
| `components/console/{types,api}.ts` | ✅ clean | `decisionTone`, generics, DTOs sound |
| `components/console/views/Painel.tsx` | ✅ fixed | `React.ReactNode` → imported `ReactNode` (removes the ambient-React dependency a reviewer flagged); `MiniTopology`/`FlowStrip` typed; decision-bar template literal yields valid `--bc-*-line` vars |
| `views/Fluxo.tsx` | ✅ clean | `cancelledRef` guard typed; stage-status mapping total |
| `views/Conexoes.tsx` | ✅ clean | dead `fetchData`/`HUB_Y_CENTER`/`useCallback` removed; no remaining refs |
| `views/Politicas.tsx` | ✅ clean | badge `intent-catalog`; both effects guarded |
| `views/Auditoria.tsx` | ✅ clean | `useRef` imported; StrictMode-safe mounted guard |
| `views/Metricas.tsx` | ⚠️ verify | see finding M1 |

## Findings

- **P1 — Painel `React.ReactNode` → `ReactNode`** — *fixed*. Was relying on the ambient React global; now an explicit `import { type ReactNode }`. (Not a hard error — legacy files use the ambient global and `tsc` passed earlier — but cleaner and removes doubt.)
- **M1 — Metricas possibly-unused helpers (LOW, non-blocking)** — `Metricas.tsx` defines `MetricTile`, `ms`, `rateTone`; confirm each is referenced in the render. If any is unused, `next lint` emits a **warning** (not an error) and `tsc` is unaffected (`tsconfig` has no `noUnusedLocals`). So it won't fail the build — just tidy if flagged.
- **Backend (separate from this review):** the real first-run risk is `lint-imports` (`backend/pyproject.toml` `ignore_imports` use `backend.*` qualified names) — covered in `VERIFICATION_HANDOFF.md` risk #2.

**Bottom line:** the frontend should be at/near `tsc`-clean. The likely real failures on a live run are NOT type errors — they're (a) `lint-imports`, (b) any e2e tab assertion sensitive to the rail, (c) visual tuning. Run `npx tsc --noEmit` to confirm; paste anything it flags.

---

## Draft A — Phase 2a starter: global design tokens (review before applying)

> Safe + additive: adding a `:root` block changes **nothing** visually until existing rules
> point at the vars. Add this at the **top of `app/globals.css`**, then converge rules
> one at a time (keep class names → e2e-safe), reloading as you go.

```css
:root {
  --app-bg: #0f172a;        --app-surface: #1e293b;     --app-surface-2: #172033;
  --app-border: #334155;    --app-border-soft: #273449;
  --app-text: #e2e8f0;      --app-text-dim: #94a3b8;    --app-text-mute: #64748b;
  --app-accent: #6366f1;
  --app-pass: #14532d;      --app-pass-text: #86efac;
  --app-flag: #422006;      --app-flag-text: #fde68a;
  --app-block: #7f1d1d;     --app-block-text: #fecaca;
  --app-reask: #4c1d95;     --app-reask-text: #c4b5fd;
}
```

Example conversions (the pattern — do the rest incrementally):
```css
body            { background: var(--app-bg); color: var(--app-text); }
.card           { background: var(--app-surface); border-color: var(--app-border); }
.badge.passthrough { background: var(--app-pass);  color: var(--app-pass-text); }
.badge.flag        { background: var(--app-flag);  color: var(--app-flag-text); }
.badge.escalate    { background: var(--app-block); color: var(--app-block-text); }
```
Why this way: one stylesheet = single source of truth → restyles all ~30 legacy panels at once, and because the class names are unchanged the 27 e2e keep passing.

---

## Draft B — Phase 5 step-1 wiring: `_CACHE` → Redis behind a flag (review before applying)

> The smallest stateless win (D.6 step 1). The adapter + factory already exist
> (`scale/cache_redis.py`); this just routes through it. Behavior is identical when
> `REDIS_URL` is unset (returns the in-process cache). Lookup/store call sites do NOT change.

In `backend/server.py`, near the other dual-import shims, add:
```python
try:
    from scale.cache_redis import get_cache
except ImportError:  # package-mode
    from backend.scale.cache_redis import get_cache
```
Then change the cache construction (currently ~`server.py:331`):
```python
# before
_CACHE = SemanticCache(similarity_threshold=0.85, max_entries=200, max_age_seconds=300.0)
# after — Redis-backed iff REDIS_URL is set, else the same in-process cache
_CACHE = get_cache(SemanticCache(similarity_threshold=0.85, max_entries=200, max_age_seconds=300.0))
```
Verify: `pytest scale/test_cache_redis.py` (fakeredis) green; then `REDIS_URL=redis://localhost:6379/0` + a manual `/query` repeat shows a cache hit across two app processes. Rollback = unset `REDIS_URL` (or revert the one line).

> Do NOT apply Draft B blind — `server.py` is the composition root + I can't run the suite here. Apply, then run `pytest -q` + the cache test before trusting.
