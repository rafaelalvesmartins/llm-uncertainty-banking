# Console — two-session coordination

Two Claude sessions have been editing this frontend at the same time, and it shows:
both are doing UX/clarity work on the same files. On **2026-06-24** a mid-edit save on
`Fluxo.tsx` (one session adding horizontal scroll to the trace while the other had
unrelated edits in flight) left the Next.js dev server showing a JSX **syntax error**
until the next valid save. This note proposes a split so that stops happening.

## Hot files — touched by BOTH (last ~25 commits)

`Painel.tsx` (6) · `Conexoes.tsx` (6) · `SessionsPanel.tsx` (3) · `Metricas.tsx` (3) ·
`Fluxo.tsx` (3) · `Auditoria.tsx` (3)

## Proposed ownership (please confirm / adjust)

**Session A — view-level copy & the Connections flow**
- `components/console/views/`: `Conexoes.tsx`, `Fluxo.tsx`, `Metricas.tsx`,
  `Politicas.tsx`, `Sessoes.tsx`, `Observabilidade.tsx`, `Configuracao.tsx`
- `components/console/DecisionLegend.tsx` (shared — single source of truth for the
  plain-language Pass/Flag/Re-ask/Escalate meanings; reuse it, don't re-explain)

**Session B — dashboard, panels & platform**
- `components/console/views/`: `Painel.tsx`, `Auditoria.tsx`, `Governanca.tsx`
- `components/*Panel.tsx` (SessionsPanel, ControlsPanel, OpsPanel, DriftPanel,
  VisibilityPanel, ActiveConfigsPanel, GovernedChangesPanel) and `ChannelFirewall.tsx`
- `backend/**` — including the governed-intent runtime overlay (Phase 2:
  `server.py`, `routers/governance_changes.py`, `routers/discovery.py`)

> Note: the view files (Session A) are thin wrappers; the live controls/decisions they
> describe live in the panel components (Session B). So view-level *copy* and panel-level
> *behavior* rarely collide — keep that boundary.

## Protocol (keeps the dev server green)

1. **Pull before you start** on a file; **commit small and often** so windows are tiny.
2. **Never leave a file half-saved.** The dev server recompiles on every save — an
   unclosed tag/brace breaks the whole tab for the other session. Save only complete edits.
3. **Touching the other session's file?** Say so first, or make the edit + commit it
   immediately (don't sit on an uncommitted cross-boundary change).
4. **One `next dev` only** (port 3002); backend on 8000, demo-safe (`BRIDGE_DEMO_SAFE=on`).
5. Stage **only your own files** when committing (`git add <path>`, not `git add -A`).

## Shared DOM contracts (don't break silently)

- `Politicas.tsx` exposes `id="propose-policy-form"` on the propose-policy card.
  `ChannelFirewall.tsx`'s "Add a request type" link opens the Advanced `<details>` and
  scrolls there. Keep that id (and the "Advanced" `<summary>` text) if you refactor —
  or grep for `propose-policy-form` first. The link has a text-match fallback, but the
  id is the reliable path.
- `ConnectionGovernance.tsx` exposes `id="propose-provider-name"` on the propose-form
  name input. `Conexoes.tsx`'s "＋ New connection" button expands the advanced section
  and scrolls/focuses it. There is NO text-match fallback — renaming the id makes that
  button a silent no-op, so grep for `propose-provider-name` before refactoring.

## Pending asks across the boundary

- **Audit absorbed the by-customer view** (2026-06-24): `Auditoria.tsx` now has a
  `[Newest first | By customer]` toggle that renders `<SessionsPanel embedded />` (same records,
  two views). The standalone **Sessions** tab is now redundant — Session A, please remove it from
  the nav + `Sessoes.tsx` when convenient (harmless to leave, just duplicate).

## Flow-coherence backlog (24-finding review, 2026-06-24)

Session B ran a full flow-coherence review (24 verified findings). Session A is also fixing
coherence (`a28b838`, `6dbf516`) — **check what's already done before starting an item.** This
is the de-duplicated backlog so the two sessions divide instead of collide.

### Needs a product call (Rafael) — IA, spans both sessions
- 🔴 **Dashboard / Observability / Metrics show the same KPIs.** Decide each tab's role:
  Dashboard = lean glance · Observability = deep health · Metrics = fold into Observability or
  rebrand "Performance trends" (history/export). Then move Painel's "Process analytics" fold to match.
- 🟡 **Policies → Governance split** (propose in Policies, approve in the Governance tab) while
  Connections does it inline. Decide: surface pending-approvals in Policies, or a clear handoff.
- 🟡 **Sessions tab** — remove it (Audit absorbed it; see "Pending asks" above).

### Session A (views)
- 🔴 **Threshold slider is direct/ungoverned but sits next to the governed form**, no signal —
  add a "Direct · no approval" note by the slider (Politicas).
- 🔴 **FLAG vs REASK conflated.** FLAG = answer RELEASED + flagged for review; REASK = answer
  WITHHELD. Fix in the Fluxo legend + Politicas threshold chart ("Below → FLAG (answered+reviewed)
  or REASK (withheld)"). Canonical wording lives in DecisionLegend.
- 🔴 **DQ-rule proposals are governed but have NO runtime effect** (only intents do). The success
  message implies they apply — add "recorded as evidence; not yet enforced at runtime" (Politicas).
- 🟡 Guard threshold is LIVE but buried in "Advanced" with no hint · propose form buried (≥3 clicks) ·
  REASK explain says "supported language" but there's no language stage (Fluxo) · real vendors can be
  proposed/approved but block at apply in demo-safe — clarify it's a server-mode block, FakeBackend isn't the lever (Conexoes).
- 🟢 Flow intro: add "click a box to see its log" · Connections vs Config provider-list overlap · "Demo" badge conflates LLM-canned with pipeline-LIVE (ConsoleShell/Whatsapp/HowThisWorks).

### Session B (mine) — mostly done
- ✅ Dashboard funnel surfaces FLAG (`c3f4302`) · "canned" label standardized in my files (`b582ad9`,`c3f4302`) · firewall "channel" scope clarified.
- ⬜ Approve/apply button styling differs (mine: ChannelFirewall/GovernedChangesPanel; A: ConnectionGovernance) — a shared `<ChangeRowActions>` would unify (cross-boundary, low).
- ⬜ Painel FlowStrip "Guard" stage has no link to Policies (low).

### Shared — DecisionLegend.tsx
- Canonical FLAG/REASK wording is the single fix-point for the FLAG/REASK conflation above. Whoever edits it: commit immediately (both sessions consume it).

_Living doc — edit the split if it doesn't match how you're actually working._
