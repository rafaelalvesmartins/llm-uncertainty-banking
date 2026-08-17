# Project Review & Product Plan — Bridge Console

> A review of the whole project + a plan to fix the three things that feel off:
> the **flow doesn't navigate**, you **can't create/edit elements**, and
> **Connections is a dead-end**. Date: 2026-06-15.

---

## 1. What I reviewed — the honest verdict

The app is now **one console** (the unification is done) and the bones are strong:
a real **12-stage inspection pipeline**, a **tamper-evident audit chain**, an
**honesty layer** (live/demo/not-configured), and a **working governance backend**
(`/api/governance/changes`) that already enforces submitter ≠ approver (SR 11-7).

But three real UX problems — the ones you felt:

1. **The flow isn't navigable.** The Dashboard's `Input → Sanitize → Intent → Guard
   → Backend → Audit → Response` strip *looks* like a map, but the boxes don't go
   anywhere. The flow is a picture, not a path.
2. **You can't create/edit.** Connections' "＋ New" is disabled; Policies/Config
   don't let you author rules; the only real CRUD (Governed Changes) is buried and
   uses its own wording. Nothing feels like "add an object."
3. **Connections is a dead-end.** It lists providers and their health, but you can't
   add, edit, or remove one — which is exactly the "create/edit elements" you want.

Root cause: each screen invents its own verbs and some paths go nowhere. There's no
single loop to learn.

---

## 2. The core idea — one loop, everywhere

Every screen should be a variation of the same loop a firewall uses:

> **create → configure → stage → approve → deploy → monitor**

Learn it once, use it everywhere. This is what removes the "confusing" feeling.

---

## 3. The plan

### Part A — The Flow strip becomes the navigation spine `[frontend]`
Make each Dashboard flow box a real link to the screen that configures that stage:
Input/Sanitize → request policy, **Intent → Intent Catalog**, **Guard → Policies**,
**Backend → Connections**, **Audit → Audit**, **Response → Observability**. Add a
hover state + a small "configure" affordance. The diagram *becomes* the menu — the
firewall packet-path view. *(Build-verifiable here: tsc + next build.)*

### Part B — One Create/Edit pattern, everywhere `[frontend + some backend]`
A single primary **"＋ Add"** button, top-right of every list (Connections, Policies,
Intents, DQ Rules), opening an **identical-feeling slide-over form** that always ends
in **Save to staging** / **Cancel**. Same fields, same validation, same success toast —
so muscle memory transfers between sections. Saving never goes live; it **stages**
(Part C). *(Frontend; needs backend staging endpoints for object types that don't have
them yet.)*

### Part C — The Pending Changes tray (staged deploy) `[frontend on the existing backend]`
The centerpiece. Every create/edit/delete drops into one global **Pending Changes**
tray, surfaced as a top-bar badge ("Pending (2)"). The review panel shows each staged
change — *what*, *who*, *when*, before/after diff — and the actions **Approve /
Decline / Deploy**. Nothing affects the live system until **Deploy**. This is mostly
**re-presenting the governance backend you already have**, turned from a buried list
into a "shopping cart → checkout" flow. Keep the SR 11-7 rule and make it legible:
when Approve is disabled, tooltip — *"You submitted this change; a different validator
must approve it."* That one tooltip removes most of the confusion.

### Part D — Connections as real provider management `[frontend + backend]`
Turn Connections from a read-only list into **create / edit / remove of providers**,
built on the **provider plugin architecture already scaffolded in `core/providers.py`**:
a provider (an LLM backend today; cloud/infra later) is add/remove by config. "＋ Add
connection" → pick a type (Ollama / OpenAI / Anthropic / …) → enter endpoint/secret →
**stages** a change → **deploys**. The health dots already exist. *(UI is frontend; the
provider registry + config-write endpoints are backend — see PROVIDER_PLUGIN_ARCHITECTURE.md.)*

### Part E — Roles & real auth `[BACKEND — your developer, not me]`
The loop needs three explicit roles: **Analyst** (creates/submits, can't approve own),
**Validator** (approves/declines others' changes, deploys), **Admin** (manages users).
A **Users & Roles** screen under Config. But the app today says "no real auth (v6
phase)", so this is **real auth + a users/roles table + login** — the heaviest lift,
and a **security-sensitive access-control change a human must implement and own**
(mis-assigning who can deploy can expose the system). I'll scaffold the *Users & Roles
screen* (UI); the auth itself and who-can-approve are your developer's, deliberately.

### Part F — Monitoring as the payoff `[frontend]`
After a Deploy, show a confirmation that **links straight to Audit** so the user sees
the change take effect. On each policy/connection row, show a small **"hits / last
triggered"** stat — firewall rule-hit counters — so people can see which rules are
actually doing something. Metrics/Audit/Observability already work; just tie them to
the loop.

---

## 4. What I can verify here vs. what's backend / your dev

| Part | I build + verify (tsc/build) | Needs backend / your dev |
|---|---|---|
| A — Flow spine | ✅ | — |
| B — Create forms | ✅ UI | staging endpoints for new object types |
| C — Pending tray | ✅ UI | (uses the existing governance backend) |
| D — Connections CRUD | ✅ UI | provider registry + config-write endpoints |
| E — Roles/auth | ✅ Users screen UI only | ⛔ real auth + access-control (security) |
| F — Monitoring | ✅ | — |

---

## 5. Build order (and a prerequisite)

**Prerequisite — land what exists first.** Run `verify.sh`, the UI translation, and
**commit** (see `CLOSEOUT_CHECKLIST.md`). Build this on a green, committed base — not
the current uncommitted pile.

Then:
1. **A + B** — routes + one create form, so the app stops feeling broken.
2. **C** — the Pending Changes tray (centerpiece; fixes the approval confusion).
3. **D** — Connections becomes real provider management.
4. **E** — auth + roles + Users screen (your dev; heaviest lift).
5. **F** — monitoring polish (those screens already function).

---

## One-line summary

Turn the scattered screens into one **create → stage → approve → deploy → monitor**
loop: the Flow strip becomes the menu, every list gets the same "＋ Add → stage" form,
a global **Pending Changes tray** replaces the buried governance list, and **Connections
becomes real provider management** on the plugin registry — with **auth/roles** as the
one backend piece your developer must own.
