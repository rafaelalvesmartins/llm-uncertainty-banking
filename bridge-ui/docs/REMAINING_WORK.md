# Bridge — Remaining Work (what's NOT done)

## 0. Honest status

The Bridge product (branch `product/bridge-platform`) is in a **green-but-uncommitted** state: 38 files across 7 logical slices are written, the real on-disk source compiles and builds clean (frontend `tsc --noEmit` strict + `next build` exit 0; backend `ruff` passes; scale-layer pytest 39 passed/5 skipped), and the prior "syntax error" scares were traced to a Linux-sandbox mount serving truncated snapshots — **not** real defects. But three things are genuinely incomplete and must be stated plainly: (a) the **PT→EN translation is partial** — ~364 accented lines remain across 39 files; a single script run clears ~200, but ~80 long-tail strings need dictionary additions and ~44 dynamic/template strings need code refactoring; (b) **the create→approve→deploy→monitor "loop" is not built** — create/approve/list mechanics exist, but there is **no `/apply` executor, no per-kind stores, no per-rule hit counters, and no real auth/login**; the loop can stage a change but cannot deploy or monitor it; and (c) the working tree is **blocked by 3 junk-message commits** and several human-only decisions (dormant nested CI, repo split, commit protocol). Nothing here is committed yet — all verification/commit steps must run **on the user's machine, never the sandbox** (no ML stack, 4 GB).

---

## 1. IMMEDIATE closeout (user's machine only)

> All commands assume repo root `c:\code\eb2niw` and branch `product/bridge-platform`. **Do not run gates in the sandbox** — it lacks torch/transformers and git-hook access.

### 1.1 Run the translation script (S, needs-human)
```powershell
# UTF-8 mode is MANDATORY — the dict has accented PT; cp1252 will crash.
cd c:\code\eb2niw
python -X utf8 _reorg/translate_ui_to_en.py --dry-run   # review planned replacements first
python -X utf8 _reorg/translate_ui_to_en.py             # apply: ~343 replacements, 41 files
git diff --stat                                          # sanity-check scope
```
Expected: ~200 category-A lines resolved immediately; ~164 accented lines remain (categories B/C/D — see §2).

### 1.2 Configure the pre-commit guard BEFORE committing (S, needs-human)
```powershell
cd c:\code\eb2niw
git config core.hooksPath 09_Projeto_GitHub/.githooks   # arms truncation pre-commit hook
```

### 1.3 Run the gates locally (M, needs-human)
```powershell
# Frontend
cd c:\code\eb2niw\09_Projeto_GitHub\llm-uncertainty-banking\bridge-ui\frontend
npm run lint; npx tsc --noEmit; npm run build
npx playwright test e2e/polish.spec.ts e2e/tabs.spec.ts   # update assertions if text changed

# Backend (full stack — requires torch/transformers installed locally)
cd c:\code\eb2niw\09_Projeto_GitHub\llm-uncertainty-banking
$env:BRIDGE_USE_REAL_LLM="off"; $env:BRIDGE_AUDIT_DB=":memory:"
.\scripts\verify.ps1
```
Baselines to match: **pytest 292 passed / 16 skipped, mypy ~38, lint-imports 3 contracts / 0 broken.** Treat deviations from these as regressions to investigate, not noise.

### 1.4 Resolve the 3 junk commits, then commit slices in order (M, needs-human)
First squash the placeholders `7c89351 (fasa)`, `e449d54 (fasda)`, `a4b8d68 (da)`:
```powershell
git rebase --onto main main product/bridge-platform   # then squash; -i is NOT supported in this env — do interactive rebase in a real terminal
```
Then commit the 7 slices (separate commits recommended; order matters for reviewability):
1. **Slice 5** — `backend/core/providers.py` (foundation, no side effects)
2. **Slice 1** — console unification (11 files: ConsoleShell, 4 views, Painel/Fluxo, app/console, app/legacy, next.config.js)
3. **Slice 2** — e2e specs (5 new + rewrites) — *verify after slice 1*
4. **Slice 4** — `backend/test_feature_map.py`
5. **Slice 6** — `scripts/verify.{sh,ps1}`
6. **Slice 3** — CI relocation: add `.github/workflows/{bridge-ui,ci}.yml`, then `git rm` the dormant nested copies (see §5.1)
7. **Slice 7** — docs (10 files; no code)

Pre-commit sanity:
```powershell
git status --porcelain   # MUST show only adds/modifies — NO mass deletions
```
The translation work (§1.1) folds into the slice-1 commit or a dedicated `Translate bridge-ui UI PT→EN` commit.

---

## 2. Translation backlog (PT→EN)

364 accented lines, 39 files. Script source: `c:/code/eb2niw/_reorg/translate_ui_to_en.py` (T dict, lines 31–265).

### Category A — in dict, awaiting script run (~200 lines · S · auto)
Resolved by §1.1. No manual work. Highest-density files:
- `lib/featureMap.ts` — 39 lines (all feature descriptions)
- `components/Metrics.tsx` — 33 · `components/Pipeline.tsx` — 18 · `components/CalibrationPanel.tsx` — 19
- `components/console/views/Politicas.tsx` — 17 · `Metricas.tsx` — 17 · `Conexoes.tsx` — 10
- `components/InfoPanels.tsx` — 16, plus EvidencePackage, VisibilityPanel, FleetInventory, DriftPanel, HowThisWorks, RegulatoryCoverage, GovernedChangesPanel, OpsPanel, ModelCard, IntentsPanel, IntegrationsPanel, ExplainModal, SessionsPanel, PlaygroundPanel, ControlsPanel
- `app/page.tsx` (22 lines: tab labels lines 40–45, walkthrough 61–69, DEMO MODE block 192–211), `app/console/layout.tsx:6`, `app/layout.tsx:8`
- `e2e/polish.spec.ts` (lines 21,44,60,83 — "Ver demonstração"), `e2e/tabs.spec.ts` (60,80 — "Catálogo")

### Category B — long-tail NOT in dict (~80 lines · M · needs-human)
Add to T dict, then re-run with `--dry-run` to confirm coverage. Concrete additions:
| PT | EN | Site |
|---|---|---|
| Não foi possível carregar intents | Could not load intents | `Politicas.tsx:189` |
| Família | Family | `Politicas.tsx:205` |
| Decisão padrão | Default decision | `Politicas.tsx:207` |
| Confiança &ge; limiar | Confidence ≥ threshold | `Politicas.tsx:161` |
| Erro ao carregar auditoria | Error loading audit | `Auditoria.tsx` |
| maiores variações | largest variations | `DriftPanel.tsx:190` |
| mudança no mix de decisões | change in decision mix | `DriftPanel.tsx:233` |
| testar adulteração | test tampering | `EvidencePackage.tsx:198` |
| enum risk `{alto, médio, baixo}` | `{high, medium, low}` | `FleetInventory.tsx:28` |
| map values `bancário`/`segurança` | `banking`/`safety` | `IntentsPanel.tsx`, `Politicas.tsx` |

Files: `_reorg/translate_ui_to_en.py` (dict), `Politicas.tsx`, `Auditoria.tsx`, `DriftPanel.tsx`, `EvidencePackage.tsx`, `FleetInventory.tsx`, `IntentsPanel.tsx`.

### Category C — dynamic/template literals (~44 lines · M · needs-human)
Cannot be string-replaced; extract to constants/helpers. Concrete refactors:
```ts
const FILTER_PLACEHOLDER = 'filter by intent';                          // Metrics.tsx:454
const ageFmt = (s:number) => s<60?`${s}s`:s<3600?`${Math.round(s/60)}min`:`${Math.round(s/3600)}h`;  // Metrics.tsx:584-587
const stageConfidence = (c:number) => `Stage confidence: ${(c*100).toFixed(0)}%`;  // Pipeline.tsx:196
```
Files: `Metrics.tsx`, `Pipeline.tsx`, `ControlsPanel.tsx`, `DriftPanel.tsx`, `OpsPanel.tsx`, `PlaygroundPanel.tsx`, `ExplainModal.tsx`. **Not gate-blocking** (code is valid), but required for complete i18n.

### Category D — console views, mixed A/B (~40 lines · S · mostly auto)
`Auditoria.tsx` (2), `Conexoes.tsx` (10), `Metricas.tsx` (17), `Politicas.tsx` (17). Stub views to verify (<10 lines each if any): `Observabilidade.tsx`, `Governanca.tsx`, `Configuracao.tsx`, `Sessoes.tsx`. Most clear with §1.1 + §2-B.

**Verify after all three passes:** `npm run lint && npx tsc --noEmit && npm run build && npx playwright test e2e/polish.spec.ts`. If e2e fails on text, update assertions to the new English strings.

---

## 3. Console completeness fixes (dead-ends / disabled / not-configured)

The console has **10 reachable views** (hash routing `#painel`…`#configuracao`) — navigation is complete and no panel is orphaned. The gaps are within panels:

### By-design limitations (honest, documented — NOT bugs, leave as-is)
- **Conexoes "＋ Nova conexão"** — permanently `disabled` with `switch_note` tooltip (backends fixed at startup). `Conexoes.tsx:361-375`.
- **Politicas / ControlsPanel backend selector** — `STATIC` badge, "definido no startup — não trocável em runtime". `Politicas.tsx:146-160`, `ControlsPanel.tsx:146-160`.
- **AssistantPanel / PlaygroundPanel** — honest Ollama-unavailable degradation, no fabricated answers.

### Real fixes needed
| Item | State | Fix | Effort | Owner |
|---|---|---|---|---|
| **VisibilityPanel content-draft approval** | partial | Frontend fires `POST /api/visibility/content/{id}/approve\|reject` but backend has **no post-approval workflow** (publish/queue). Wire backend governance flow. `VisibilityPanel.tsx:139-199` | M | **human** |
| **Painel topology "＋ New"** | partial | Pure label, no `onClick`/`disabled` — UX-inconsistent vs Conexoes' explicit disable. Either disable+tooltip or link to `#conexoes`. `Painel.tsx:159-173` | S | auto |
| **ModelCard / CalibrationPanel** | partial | Listed in Observabilidade but uninspected — verify they hit real endpoints (`/api/model-card`, `/api/calibration`) and aren't rendering placeholder "no data" over an incomplete backend. | M | auto |
| **GovernedChangesPanel apply** | blocked | No deploy path — see §4 Part B. | L | auto→human (auth) |

**Verified-live (no action):** Auditoria (chain verify), Painel (drill-through), Fluxo (pipeline trace), Metricas (9 KPIs), Sessoes (session log), Configuracao (settings PUT), DriftPanel auto-rebaseline, HowThisWorks honesty layer (forward+reverse OpenAPI cross-check).

---

## 4. The loop (A–F/E): create → approve → deploy → monitor

**What works today:** submit (`POST /governance/changes`), list (`GET`), decide (`POST .../decision`) in `backend/routers/governance_changes.py`; `GovernedChangesPanel.tsx` renders a flat list with status badges and approve/reject buttons. **What's missing:** the entire deploy + monitor half, all per-kind stores, and real auth. The loop stages but cannot enact.

### Part A — Nav spine (S · auto · *partial*)
7-box Flow strip in `Painel.tsx` is **visual-only** — no handlers linking boxes to config screens. **Build:** add `onClick` per box → navigate to `#governanca`/`#conexoes`/`#politicas`/`#auditoria`.
Files: `ConsoleShell.tsx` (CONSOLE_VIEWS), `Painel.tsx` (STAGES).

### Part B — Create/Edit forms + executor (L · auto · *not-started*) ← **core gap**
Missing: (1) generic `AddSlideOver.tsx` (does not exist) reusable across kinds; current inline 3-field form doesn't match the 4.1 payload (`op/target_id/before/after`). (2) **`POST /governance/changes/{id}/apply` endpoint** — does not exist. (3) `apply()` registry + `apply_policy/apply_dq/apply_intent/apply_provider`. (4) optimistic-concurrency re-read-before-snapshot. (5) idempotent store mutation. (6) Audit row write on apply. (7) schema columns `applied_by/applied_at/audit_seq` (current schema only has `submitted_by/submitted_at/reviewer/decided_at/decision_note`).
**Cheapest first kind = policy** (read-site already live, see Part M2). 
Files: `backend/routers/governance_changes.py`, `backend/models.py`, `backend/routers/audit.py`, new `frontend/components/AddSlideOver.tsx`, `GovernedChangesPanel.tsx`.

### Part M2 (policy foundation, subset of B) — (S · auto · *done-uncommitted read-site*)
**Live read-site already consumes the value** — this is the cheapest deploy to wire end-to-end:
- `_RUNTIME_GUARD_THRESHOLD` / `_RUNTIME_CACHE_ENABLED` are live mutable scalars in `server.py:337-338` (proxied by `_ProxyingServerModule`).
- Read every `/query` guard stage: `server.py:1113, 1280`; cache check: `server.py:1085, 1298, 1306`; also `model_card.py:46`, `security.py:93`, `visibility.py:428/616`.
- `PUT /settings` already mutates them: `routers/settings.py:94-96`.
**To complete:** submit `kind='policy'` change → `apply_policy()` sets the scalar via server proxy + writes Audit row → add schema columns → `/apply` endpoint.

### Part C — Pending Changes tray (M · auto · *partial*)
Have: list + per-change approve/reject. **Missing:** (1) top-bar "Pending (n)" badge in `ConsoleShell.tsx`; (2) before→after diff UI (payload `before/after` not unpacked); (3) Apply button on approved changes; (4) post-apply success toast + link to Audit row; (5) surface `sod_enforced`/`sod_warning` ("not cryptographically enforced when BRIDGE_AUTH=off") in the UI.
Files: `ConsoleShell.tsx`, `GovernedChangesPanel.tsx`, `app/api/governance/changes/route.ts`, `.../[id]/decision/route.ts`.

### Part D — Connections provider management (M · auto · *blocked*)
`Conexoes.tsx` "＋ Add Connection" not wired. Backend: `core/providers.py` defines `Registry`/`@register_backend` but **`backends._select_backend()` ignores the registry** — it uses hard-coded `OLLAMA_URL` probe logic. Missing: registry resolve wiring, config-instance writer (persist user endpoints), `apply_provider()`, per-provider read-site. Blocked on Part B's store+apply infra.
Files: `Conexoes.tsx`, `core/providers.py`, `backends.py:_select_backend()`, `routers/integrations.py`.

### Part F — Monitoring: per-rule hit counters (M · auto · *not-started*)
No per-rule counter infra anywhere. `routers/metrics.py` exposes `/metrics /stats /queue/depth /stages/budgets` but none aggregate by rule ID; no increment site in guard/dq stages; audit rows lack the consulted rule ID. **Build:** add rule-ID increment at guard/dq-check stages, aggregate endpoint, "hits / last triggered" stat per policy row, and post-deploy link from applied change → its Audit row.
Files: `routers/metrics.py`, `routers/observability.py`, `server.py` (increment site), `routers/audit.py` (rule ID in schema), `GovernedChangesPanel.tsx`.

### Part E — Auth & roles (L · **HUMAN / SECURITY** · *not-started*)
Seam exists, enforcement does not. `routers/auth.py` has EdDSA JWT sign/verify (**demo-only ephemeral key**), `/auth/token` with **hardcoded** demo users (`ana.analista`, `bruno.validador`, `carla.mrm`), `verify_token`, and a role check in `decision_endpoint`. **Missing:** real IdP/LDAP/OAuth, persistent user store (currently in-memory dict), login UI (frontend never calls `/auth/token` → role check is unreachable), Users & Roles admin screen. `BRIDGE_AUTH` defaults `off` → `verify_token` returns None, `submitted_by`/`reviewer` unverified. **This is a security-owned decision: do not ship apply/deploy to a real environment until Part E is real** — without it, segregation-of-duties is cosmetic.
Files: `routers/auth.py`, `routers/governance_changes.py:decision_endpoint`, `GovernedChangesPanel.tsx`, `Configuracao.tsx`.

### Foundational — per-kind writable stores (L · auto · *not-started*)
Greenfield except policy. **Policy:** scalars live but not persisted across restart. **DQ rule:** none — `DataQualityChecker` uses hard-coded `default_input_rules/output_rules`, no table, no writer. **Intent:** `_INTENT_CATALOG` is `Final` in `core/classifier.py:784` with no writer, and `classify_intent` doesn't even read it (hard-coded marker tuples). **RAG doc:** `InMemoryDocumentStore`, no persistence/writer. Frontend accepts `kind ∈ {agent,intent,dq_rule,rag_doc,other}` but **no backend storage exists for any**.
Files: `server.py`, `core/classifier.py`, `backend/state/`, `routers/governance_changes.py`.

---

## 5. Decisions the human must make

### 5.1 Dormant nested CI (M · needs-human)
`09_Projeto_GitHub/llm-uncertainty-banking/.github/workflows/` holds 5 YAMLs (`bridge-ui`, `ci`, `release`, `docs`, `nightly-calibration`). GitHub Actions **only scans `<repo-root>/.github/workflows/`**, so all 5 are inert. The activated copies are `c:/code/eb2niw/.github/workflows/{bridge-ui,ci}.yml`.
- **Recommended:** `git rm` the dormant `bridge-ui`/`ci` copies, document in a CI comment that the nested `.github/` is intentionally inert, and defer (to Phase 5+) whether to **split `llm-uncertainty-banking` into its own repo** so its `.github/` sits at root.
- **Consequence of keeping:** `release.yml`/`docs.yml`/`nightly-calibration.yml` reference `src/lub/...` paths that don't exist at monorepo root → they cannot run until relocated or the repo is split.

### 5.2 Dockerfile comment (S · auto)
`bridge-ui/backend/Dockerfile:36` `pip install .../llm_uncertainty_banking-*.whl` is **correct** (distribution name ≠ import name `lub`). Only fix: move the "Do NOT `pip install lub`" warning from the README into the Dockerfile (line 26) to prevent copy-paste errors. Code is sound.

### 5.3 Junk commits (M · needs-human)
`7c89351 (fasa)`, `e449d54 (fasda)`, `a4b8d68 (da)` on `product/bridge-platform` block clean integration. **Recommended:** squash now (rebase onto `main`) before the slice commits, so slices 1–7 autosquash cleanly. `git rebase -i` is **not supported in this env** — run it in a real terminal.

### 5.4 Verify protocol (S · needs-human)
Gates require the full `lub` stack (torch/transformers, multi-GB) + git hooks — the sandbox cannot run pytest/mypy/lint-imports. **Protocol:** user runs `verify.ps1` locally → green before commit → CI re-runs the same gates on PR → pre-commit hook blocks truncation. Operational constraint, not a code change.

---

## 6. Prioritized sequence (M1–M5)

**M1 — Close out what's green (today, user's machine).** §1 in order: run translation (§1.1), arm hook (§1.2), run gates (§1.3), squash junk commits + commit slices 5→1→2→4→6→3→7 (§1.4), resolve dormant CI (§5.1). *Exit: working tree clean, gates green, branch integrated.* — M, needs-human.

**M2 — Finish translation.** §2-B dict additions → re-run script → §2-C dynamic-string refactor → e2e assertions updated → gates green. *Exit: 0 accented lines, e2e passes.* — M, needs-human.

**M3 — Build the policy deploy slice (loop, end-to-end on the cheapest kind).** Part M2 + Part B for `kind='policy'` only: schema columns (`applied_by/applied_at/audit_seq`), `apply_policy()`, `POST /apply`, Audit write; then Part C frontend (pending badge, diff, Apply button, post-deploy toast+link). *Exit: a policy threshold change can be created → approved → applied → visible in `/query` guard + Audit.* — L, auto.

**M4 — Extend stores + monitoring.** Foundational per-kind stores (DQ rule, intent writer, RAG doc, policy persistence) + Part D (provider registry wiring + `apply_provider`) + Part F (per-rule hit counters, post-deploy Audit link) + Part A nav spine. *Exit: all `kind`s deployable; per-rule hits visible.* — L, auto.

**M5 — Real auth (security-gated).** Part E: real IdP/persistent user store, login UI calling `/auth/token`, `BRIDGE_AUTH=on` enforcement, Users & Roles screen, SoD made cryptographic. **Do not expose apply/deploy to any real environment before M5.** *Exit: SoD enforced, role checks reachable.* — L, **human/security**.

---

## 7. Operational nits (follow-up sweep, 2026-06-17)

Found after the main audit; all Small. Two FIXED in place (uncommitted), one documented.

| # | Item | State | Detail |
|---|---|---|---|
| N1 | `start-demo.sh` frontend port inconsistency | **FIXED** | killed/started/waited on :3000, but the demo runs on :3002 (e2e uses :3001). Standardized to **:3002** (`bridge-ui/start-demo.sh`: kill_port, `npm run dev -- -p 3002`, wait curl, echo). |
| N2 | `verify.ps1` truncation gate required `pwsh` | **FIXED** | line 43 used `pwsh -File` (fails if only Windows PowerShell 5.1 is present). Now `& $TruncPs -Threshold 5` (runs in the current PowerShell; falls back to the `.sh` if no `.ps1`). |
| N3 | `_reorg` scripts have no `.ps1` variants | **TODO (S)** | `reorg_fatia{1,2,3}.sh`, `run_refactor.sh`, `translate_ui_to_en.py` are `.sh`/`.py` only (works via Git Bash). Optional PowerShell ports for pure-Windows runners; `commit_unification.ps1` already exists. |

**Verified NOT gaps** (don't spend energy): `verify.ps1` is a correct full port of `verify.sh`; `app/page.tsx` is NOT orphaned (re-exported by `/legacy`); console e2e (`console.spec.ts`) exists; the Prometheus `/metrics/prometheus` endpoint is wired + live; the R1–R4 security fixes are committed; the scale layer (Track D) is intentionally deferred.
