# Bridge Console — Complete Implementation Plan
### The unified **create → stage → approve → deploy → monitor** loop

> ⚠️ **Superseded by [`IMPLEMENTATION_PLAN_V2.md`](./IMPLEMENTATION_PLAN_V2.md)** (2026-06-17, code-verified).
> V2 corrects the first apply kind (guard-threshold **policy**, not intent), names a live
> read-site per kind, and embeds the repo hazards (commit-first, truncation guard,
> dual-import/proxy). Keep this for context; **build from V2.**

> **Status:** authoritative build plan. Supersedes the *sequencing* and the *"mostly
> frontend"* estimate in `PROJECT_REVIEW_AND_PLAN.md`. Corrected build order, the
> hidden backend work surfaced and scoped, honesty rules made explicit.
> **Date:** 2026-06-17 · **Owner of backend/auth items:** the developer (see §9).

---

## 0. TL;DR

The app is already one console with strong bones: a 7‑stage inspection pipeline, a
tamper‑evident audit chain, a real governance backend that enforces *submitter ≠
approver* (SR 11‑7), and an honesty layer that labels every feature **Live / Demo /
Not configured**. Three UX problems remain: the flow **doesn't navigate**, you
**can't create or edit elements**, and **Connections is a read‑only dead‑end**.

The fix is one idea applied everywhere: **every screen runs the same loop a firewall
uses — create → stage → approve → deploy → monitor.** Learn it once, use it
everywhere.

The single most important correction to the earlier plan: **the "deploy" step does
not exist yet.** The governance backend can *submit* and *approve* a change, but
nothing *applies* an approved change to the live system. That apply/deploy executor —
plus writable stores for the object types that don't have one — is the real backend
work, and it must be built before "＋ Add" can be honest. This plan scopes it
explicitly and reorders the work so each part has something real to build on.

**Corrected order:** Prerequisite → **A → C → B → D → F → E** (the old plan put D
before C and hid the apply executor inside "Part B frontend").

---

## 1. The three problems (what you actually felt)

1. **The flow isn't navigable.** The Dashboard's `Input → Sanitize → Intent → Guard →
   Backend → Audit → Response` strip *looks* like a map, but the boxes go nowhere. It
   is a picture, not a path.
2. **You can't create or edit.** Connections' "＋ New" is disabled; Policies and Config
   don't let you author rules; the only real CRUD (Governed Changes) is buried and
   speaks its own dialect. Nothing feels like "add an object."
3. **Connections is a dead‑end.** It lists providers and their health but offers no
   add / edit / remove — which is exactly the create/edit you want.

Root cause: each screen invents its own verbs, and some paths terminate. There is no
single loop to learn.

---

## 2. The one idea — one loop, everywhere

> **create → configure → stage → approve → deploy → monitor**

Every list gets the same **＋ Add** button and the same slide‑over form. Saving never
goes live — it **stages**. Staged changes collect in one global **Pending Changes**
tray. A *different* person approves (SR 11‑7). **Deploy** applies the change. The UI
then shows it took effect, linked straight to **Audit**. That loop is the whole
product; the rest is detail.

---

## 3. Guardrails (non‑negotiable)

- **Honesty first.** No dead forms. Every "＋ Add" is backed by a real endpoint, or it
  renders as **Not configured** via the existing `StateBadge`. The app's credibility
  is that nothing pretends to work — we do not break that to look finished.
- **Build on a green, committed base.** No new feature lands on the current
  uncommitted pile (see Prerequisite).
- **Surgical changes.** Reuse the existing `change_requests` store; do **not** build a
  parallel staging system. Touch only what each part requires.
- **Deploy is gated until auth exists.** Until Part E, **Deploy** is clearly labelled a
  **demo action** and the SR 11‑7 check is shown as *not cryptographically enforced*
  (the backend already returns `sod_enforced: false` + a warning when `BRIDGE_AUTH=off`
  — surface it, don't hide it).
- **Each part ships verified.** Frontend: `tsc --noEmit` + `next build`. Backend:
  `pytest` for the touched router. No part is "done" until its checks pass.

---

## 4. What already exists (so we extend, not rebuild)

| Capability | Where | State |
|---|---|---|
| Change‑request store | `backend/routers/governance_changes.py` | **Real & persisted** (SQLite). `submit` / `list` / `decide`. Kinds: `agent, intent, dq_rule, rag_doc`. Enforces reviewer ≠ submitter (SR 11‑7). |
| Auth seam | same file + `routers/auth.py` | `verify_token` dependency, role check (`validator`/`admin`), `sod_enforced` honesty flag, `BRIDGE_AUTH` switch. **Identity provider + user store not built.** |
| Provider registry | `backend/core/providers.py` | Scaffolding only — `health` / `is_configured` / `resolve` / `register_backend`. **Additive, not yet wired** into `_select_backend()`. |
| Connections view | `frontend/.../views/Conexoes.tsx` | Read‑only topology + table; "＋ Nova conexão" disabled with an honest note. **Still in Portuguese** (translation script pending). |
| Honesty layer | `frontend/components/StateBadge.tsx` | Live / Demo / Not configured per feature. |
| Pipeline strip | `frontend/.../views/Painel.tsx` (`STAGES`) | 7 stages, static. |
| Nav rail | `frontend/.../console/ConsoleShell.tsx` (`CONSOLE_VIEWS`) | 10 views, single source of truth. |

**Reading of the change store:** it records the *intent* to change (a `payload`), and
the approval trail — but **nothing reads an approved change and applies it.** There is
no before/after snapshot (so no real diff yet), and no `delete` semantics. Those gaps
are the keystone work in §5.

---

## 5. The keystone — the staging / apply model

This is the piece the earlier plan glossed as "mostly frontend." It is the backend
spine of the whole loop. Keep it **surgical**: extend the existing store, don't add a
new one.

**5.1 Extend the change record (no schema migration).** Store the extra fields inside
the existing `payload` JSON column:

```jsonc
// payload of a change_request
{
  "op": "create" | "update" | "delete",
  "target_id": "policy-42",          // null for create
  "before": { ... } | null,           // snapshot at submit time → enables real diff
  "after":  { ... }                   // desired state (null for delete)
}
```

`op`, `before`, and `after` give the tray a true **before/after diff** and let one
code path handle create, edit, and remove.

**5.2 Add an apply/deploy executor.** A registry of `kind → apply(change)` functions:

```
apply_registry = {
  "provider": apply_provider_change,   # write config instance, re-resolve backend
  "policy":   apply_policy_change,     # write to the policy store the Guard reads
  "intent":   apply_intent_change,     # write to the intent catalog
  "dq_rule":  apply_dq_change,
}
```

`apply(change)` must: (a) require `status == "approved"` and a `validator/admin` role;
(b) mutate the live store idempotently; (c) write an **Audit** entry (this is what ties
Deploy to Monitoring); (d) mark the change `applied` with `applied_at`.

**5.3 New endpoint.** `POST /governance/changes/{id}/apply` — the **Deploy** action.
Returns the new live state + the Audit entry id. Gated by role; until `BRIDGE_AUTH=on`,
returns the same honest `sod_enforced: false` signal.

**5.4 Writable live stores per kind.** This is the real cost. Today:
- **intent** — has a catalog; confirm it is writable.
- **provider** — config‑derived, **read‑only today**; needs a config‑instance writer.
- **policy / dq_rule** — **no writable store and no router yet**; the Guard stage reads
  static config. A small persisted store (mirroring `governance_changes`' SQLite
  pattern) is needed, plus a read in the Guard stage.

Until a kind has a writable store **and** an `apply_*` function, its "＋ Add" stays
**Not configured** in the UI (Guardrail §3). That keeps the loop honest while it is
built kind‑by‑kind.

---

## 6. The plan, part by part (corrected order)

Each part: **Goal · Frontend · Backend · Endpoints · Honesty · Verify · Done‑when.**

### Prerequisite — Land what already exists
- **Do:** run `scripts/verify.sh` (gates green), run `_reorg/translate_ui_to_en.py`
  (translates the remaining Portuguese, incl. `Conexoes.tsx`), then **commit** per
  `CLOSEOUT_CHECKLIST.md`.
- **Done‑when:** clean tree, CI green, no Portuguese strings in the console.
- *Everything below builds on this commit — not the current pile.*

### Part A — The Flow strip becomes the navigation spine `[frontend only]`
- **Goal:** the pipeline diagram *is* the menu.
- **Frontend:** make each `STAGES` box in `Painel.tsx` a link to the screen that
  configures that stage — Intent→Intent Catalog, **Guard→Policies**,
  **Backend→Connections**, Audit→Audit, Response→Observability; Input/Sanitize→request
  policy. Add hover + a small "configure" affordance. Reuse the rail's `onSelect`.
- **Backend:** none.
- **Honesty:** stages whose target screen isn't built yet link to a "Not configured"
  state, not a blank.
- **Verify:** `tsc` + `next build`; the existing `e2e/console.spec.ts` extended with a
  click‑through assertion.
- **Done‑when:** clicking any stage navigates to its screen.

### Part C — The Pending Changes tray `[frontend on the existing backend]`
*(Moved ahead of B and D: both stage **into** this tray, so it must exist first.)*
- **Goal:** the centerpiece — turn the buried governance list into a "cart → checkout".
- **Frontend:** a top‑bar badge **Pending (n)** (count from `GET /governance/changes`
  `by_status.pending`); a panel listing each staged change with **what / who / when**
  and a **before→after diff** (from §5.1). Actions **Approve / Decline** (existing
  `decision` endpoint) and **Deploy** (new apply endpoint, §5.3). When Approve is
  disabled, tooltip: *"You submitted this change; a different validator must approve
  it."*
- **Backend:** none for approve/list (exists); **Deploy needs §5.2–5.3**. Ship the tray
  first against approve/decline; wire **Deploy** as part of Part B when the first
  `apply_*` lands.
- **Honesty:** show the `sod_warning` verbatim when `BRIDGE_AUTH=off`.
- **Verify:** `pytest test_governance_changes.py` (unchanged passes); FE `tsc`/build;
  e2e: submit → appears in tray → second operator approves.
- **Done‑when:** a staged change is visible, diffable, and approvable from the tray.

### Part B — One Create/Edit pattern, everywhere `[frontend + backend]`
- **Goal:** identical "＋ Add" → slide‑over → **Save to staging** on every list.
- **Frontend:** one `<AddSlideOver>` component (fields, validation, success toast)
  reused by Connections, Policies, Intents, DQ Rules. "Save" calls `POST
  /governance/changes` with the §5.1 payload — it **stages**, never goes live.
- **Backend:** the **apply executor (§5.2)** and the first **writable stores (§5.4)** —
  start with **intent** (likely closest to writable), then **dq_rule**, then **policy**.
- **Endpoints:** reuse `POST /governance/changes`; add `POST
  /governance/changes/{id}/apply`.
- **Honesty:** a kind without an `apply_*` + store shows **Not configured**, not a dead
  form.
- **Verify:** new `pytest` per `apply_*` (stage → approve → apply → live store changed →
  Audit row written); FE `tsc`/build.
- **Done‑when:** you can create one real object type end‑to‑end (stage → approve →
  deploy → see it live).

### Part D — Connections as real provider management `[frontend + backend]`
- **Goal:** add / edit / remove providers, behind the loop.
- **Frontend:** enable "＋ Add connection" → pick a **known type** (Ollama / OpenAI /
  Anthropic) → enter endpoint/secret‑ref → **stages** a `provider` change. Edit/remove
  on each row. The topology + health dots already exist.
- **Backend:** register the real backends into `backend_registry`, wire
  `_select_backend()` to `backend_registry.resolve()` (the TODO in `core/providers.py`),
  and add a **config‑instance writer** + `apply_provider_change` (§5.2).
- **Honesty (important):** you can add/configure **instances of known provider types**;
  you **cannot** add a brand‑new provider *type* without code/a plugin — the UI must say
  so (no fake "add any provider"). Secrets are stored by **reference**, never inline.
- **Verify:** `pytest` for the provider writer + resolve; FE `tsc`/build.
- **Done‑when:** a new Ollama endpoint can be added, staged, approved, deployed, and
  appears active in the topology.

### Part F — Monitoring as the payoff `[frontend + small backend]`
- **Goal:** close the loop visibly.
- **Frontend:** after Deploy, a confirmation that **links to the Audit entry** the apply
  wrote; on each policy/connection row, a small **"hits / last triggered"** stat
  (firewall rule‑hit counters).
- **Backend:** a lightweight per‑rule hit counter incremented in the Guard/Backend
  stages, exposed on the existing metrics/observability routers.
- **Verify:** `pytest` for the counter; FE `tsc`/build.
- **Done‑when:** deploying a policy and triggering it increments its visible hit count.

### Part E — Roles & real auth `[BACKEND — your developer, not me]`
- **Goal:** three explicit roles — **Analyst** (submits, can't approve own), **Validator**
  (approves/declines/deploys), **Admin** (manages users) — and a **Users & Roles** screen.
- **State:** the **seam exists** (`verify_token`, role checks, `sod_enforced`,
  `BRIDGE_AUTH`). The work is the real identity provider, a users/roles table, and
  login — i.e. turning `BRIDGE_AUTH=on` from a flag into an enforced control.
- **Why human‑owned:** this is a **security‑sensitive access‑control change**.
  Mis‑assigning who can deploy can expose the live system. I will scaffold the *Users &
  Roles screen (UI)*; the auth itself and who‑can‑approve are the developer's,
  deliberately.
- **Done‑when:** Deploy/Approve require a signature‑bound role and `sod_enforced: true`.

---

## 7. Backend work, surfaced (the part the old plan hid)

| # | Backend task | For | Size | Risk |
|---|---|---|---|---|
| B1 | Extend change `payload` with `op/target_id/before/after` (§5.1) | C, B | **S** | low |
| B2 | `apply(change)` registry + `POST …/apply` (§5.2–5.3) | C/B Deploy | **M** | med (mutates live state) |
| B3 | Writable **intent** store + `apply_intent_change` | B | **S–M** | low |
| B4 | Writable **policy / dq_rule** store + Guard reads it | B | **M–L** | med |
| B5 | Provider **config‑instance writer** + wire `backend_registry.resolve()` | D | **M** | med |
| B6 | Per‑rule **hit counters** on metrics/observability | F | **S** | low |
| B7 | Real **auth + users/roles + login** (`BRIDGE_AUTH=on`) | E | **L** | **high — security** |

Nothing here is throwaway: B1–B2 are the spine reused by every kind; B7 is the only
item that must be owned by a human.

---

## 8. Build order & milestones

- **Milestone 1 — the thin slice (ship first): Prerequisite + A + C.**
  Fixes all three felt problems — navigation, the buried governance list, the
  "confusing" approval — with **near‑zero backend risk** (A is FE‑only; C re‑presents an
  existing backend; Deploy stubbed/demo until M2). This is the highest‑value, lowest‑risk
  cut. **Do this, commit green, then reassess.**
- **Milestone 2 — make it real: B + B1/B2 + one store (intent).**
  First true create → stage → approve → **deploy** → live.
- **Milestone 3 — Connections: D + B5.**
- **Milestone 4 — Monitoring: F + B6.**
- **Milestone 5 — Auth: E + B7 (developer).**

Do **not** attempt all six at once. Each milestone is independently shippable and
verifiable.

---

## 9. Who builds what

| Part | I build + verify here (tsc/build, pytest) | Needs the developer |
|---|---|---|
| Prereq | run scripts, surface failures | **commit** (human) |
| A — Flow spine | ✅ | — |
| C — Pending tray | ✅ UI + reuse existing API | — (Deploy lands with M2) |
| B — Create forms | ✅ UI + apply executor + intent store | review of live‑mutation code |
| D — Connections | ✅ UI + provider writer/resolve | secret storage policy |
| F — Monitoring | ✅ | — |
| E — Auth/roles | ✅ Users screen UI only | ⛔ **real auth + access control (security)** |

---

## 10. Risks & mitigations

- **Dead forms break honesty.** → Guardrail: real endpoint or **Not configured**; no
  exceptions.
- **Apply mutates live state.** → B2 is idempotent, role‑gated, and writes an Audit row;
  every deploy is reviewable and reversible by an opposite change.
- **Deploy before auth = theatre.** → Deploy is labelled **demo** and surfaces
  `sod_enforced: false` until E lands.
- **Scope creep.** → Milestones are independently shippable; stop after M1 if needed.
- **Building on an uncommitted pile.** → Prerequisite blocks all parts.

---

## 11. Acceptance criteria (definition of done)

- **M1:** every Flow stage navigates; a staged change shows what/who/when + diff in the
  tray; a second operator can approve it; `tsc`/`build`/`pytest` green; no Portuguese in
  the console.
- **M2:** create one intent end‑to‑end — stage → approve → **deploy** → it is live and an
  Audit row exists.
- **M3:** add a new provider instance the same way; it appears active in the topology.
- **M4:** a deployed policy shows a live, incrementing hit count.
- **M5:** Approve/Deploy require a signature‑bound role; `sod_enforced: true`.

---

## 12. One line

Turn the scattered screens into one **create → stage → approve → deploy → monitor**
loop: the Flow strip becomes the menu (A), a global **Pending Changes** tray replaces the
buried governance list (C), every list gets the same "＋ Add → stage" form backed by a
real **apply executor** (B), Connections becomes real provider management on the plugin
registry (D), monitoring closes the loop (F) — with **auth/roles** (E) as the one
security‑sensitive piece the developer must own. Build it thin first: **A + C**, on a
green commit.
