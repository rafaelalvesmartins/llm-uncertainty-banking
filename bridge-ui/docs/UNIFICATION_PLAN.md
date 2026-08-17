# Unification Plan — one app (firewall console at the root `/`)

> **Date:** 2026-06-15 · **Goal:** a single app — the console shell (rail + topbar +
> tokens) hosting **all** the rich legacy panels. Console at `/`, no duplicate `/console`
> and no parallel legacy app, with converged styling.
> **Principle:** reuse, don't rewrite. The 30 legacy components stay; what changes is who
> hosts them and how they're styled.
>
> **Status:** largely DONE — Phases 0/2/4/5 are implemented and verified (console at `/`,
> 4 wrapper groups hosting the panels, `/legacy` preserved, e2e repointed). Phase 1
> (restyle) turned out to be a near no-op (shared palette). This doc is the record + the
> remaining detail.

---

## 1. Current state (starting point)

| Layer | State |
|---|---|
| Root `/` | rewrite → `/console` (Phase 0 ✅). `app/page.tsx` legacy preserved, shadowed. |
| Legacy (`app/page.tsx`) | **3 tabs** (`atendimento` · `observabilidade` · `catalogo`) + rail; 30 components; hash routing; ARIA tabs; `ContextBar`, `ValueStrip`, `MasonryGrid`. |
| Console (`components/console/`) | `ConsoleShell` (rail+topbar) + 10 views; contract `types.ts`/`api.ts`; scoped `.bridge-console` CSS. |
| State | `AppContextProvider` + `ConfirmProvider` in `app/layout.tsx` (root) → inherited by `/` and `/console`. |
| CSS | `globals.css` (1178 lines, shared classes) **+** `console.css` (`.bridge-console`, `--bc-*` tokens). |
| Honesty | `featureMap.ts` + `StateBadge` — **unchanged.** |
| e2e | 5 specs: `console`, `tabs`, `layout`, `polish`, `demo-smoke`. |

---

## 2. The strategy (what makes this feasible)

Three decisions that avoid rewriting 25 panels:

1. **`ConsoleShell` becomes the single app** and **hosts** the legacy components as-is
   (direct import, same props). No logic rewrites.
2. **Restyle via shared class names:** point `globals.css`'s classes (`.card`, `.badge`,
   `.control-*`, …) at the `--bc-*` tokens. Repaints all ~25 panels at once and is
   **e2e-safe** because the class *names* don't change. → *Turned out near-no-op: the legacy
   palette and the `bc-*` tokens are already the same colors.*
3. **One rail:** the 6 curated console views + the deep legacy panels, grouped. The 3 legacy
   tabs become rail groups.

---

## 3. Mapping — what becomes what (unified rail)

| Rail item (new) | Source | Components |
|---|---|---|
| **Painel** | console | overview (cards + flow + topology + events) |
| **Fluxo** | console | packet-flow query view (covers QueryPanel+Pipeline) |
| **Conexões** | console | topology + provider table |
| **Políticas** | console | guard threshold + intent catalog |
| **Auditoria** | console | hash-chain + verify |
| **Métricas** | console | decision mix + latencies |
| **Sessões** | legacy | `SessionsPanel`, `AssistantPanel`, `PlaygroundPanel` |
| **Observ.** | legacy | `Metrics`, `DriftPanel`, `OpsPanel`, `FleetInventory`, `ModelCard`, `CalibrationPanel`, `VulnerabilityScan`, `ExperimentsPanel` |
| **Governança** | legacy | `Compliance`, `RegulatoryCoverage`, `EvidencePackage`, `GovernedChangesPanel`, `VisibilityPanel`, `IntentsPanel` |
| **Config** | legacy | `ControlsPanel`, `IntegrationsPanel`, `InfoPanels`, `HowThisWorks` |

---

## 4. Phases (each verifiable; gate = the named test)

### Phase 0 — Console at the root ✅ DONE
Rewrite `/` → `/console` in `next.config.js`. (build green)

### Phase 1 — Restyle ✅ effectively no-op
Point `globals.css`'s shared classes at `--bc-*`. **Finding:** the legacy `globals.css`
already uses the same palette as the tokens (`#0f172a`, `#e2e8f0`, `#94a3b8`, green
`#14532d/#86efac`, red `#7f1d1d/#fecaca`) — `console.css` was derived from it. So the hosted
panels already harmonize; a blind 1178-line restyle would be risk without gain. Skipped.

### Phase 2 — Host the legacy panels in the shell ✅ DONE
- `ConsoleShell.tsx` — added the new rail items (Sessões/Observ./Governança/Config) + `ViewId`/`CONSOLE_VIEWS`.
- `components/console/views/` — thin wrappers that import and render the legacy panels (no logic rewrites).
- `app/console/page.tsx` — registered the new views in `VIEWS`.
Verified: `tsc --noEmit` + `next build`.

### Phase 3 — Consolidate overlaps (optional, later)
Where a console view and a legacy panel cover the same thing, pick one as primary; the other
becomes a deep detail or is dropped.

### Phase 4 — Retire duplicates ✅ DONE (via /legacy)
The legacy is preserved at `/legacy` (re-export); `/console` content serves `/` via the rewrite.

### Phase 5 — e2e ✅ DONE
`console.spec.ts` (new) validates the unified shell; `tabs/layout/polish/demo-smoke` repointed
to `/legacy`. `playwright --list` discovers all 31 tests.

---

## 5. What changed, by file

| File | Phase | Change |
|---|---|---|
| `next.config.js` | 0 ✅ | rewrite `/`→`/console` |
| `components/console/ConsoleShell.tsx` | 2 ✅ | new rail items + `ViewId` |
| `components/console/views/*.tsx` (new) | 2 ✅ | thin wrappers of the legacy panels |
| `app/console/page.tsx` | 2 ✅ | registered the new views in `VIEWS` |
| `app/legacy/page.tsx` (new) | 4 ✅ | re-export of the legacy app |
| `e2e/*.spec.ts` | 5 ✅ | new console spec; legacy specs repointed to `/legacy` |

**Untouched:** all the backend, `app/api/*` (BFF), `featureMap.ts`, `StateBadge`,
`AppContextProvider`/`ConfirmProvider`, the 30 components' logic, `console.css` (tokens).

---

## 6. Who-does-what
- **`[here]`** (verifiable without torch): the restyle assessment, the wrappers + rail, with
  `tsc`+`build` green at each step. ✅ done.
- **`[machine]`**: visual approval per phase (✅ browser-confirmed), the commit, the real
  `playwright test` run.

### One-line summary
Don't rewrite anything: `ConsoleShell` now hosts the 30 legacy panels, the navigation is one
rail, duplicates are retired (legacy at `/legacy`), and the e2e point at the new world — all
verified by `tsc` + `next build` + `playwright --list`, and confirmed at runtime in the browser.
