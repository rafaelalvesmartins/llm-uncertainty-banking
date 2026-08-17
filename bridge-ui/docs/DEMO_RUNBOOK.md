# Demo runbook — the 10-minute MRM walkthrough

The click sequence and talk track for demoing Bridge to a bank model-risk (MRM)
buyer. The console at `/` is the **only** demo surface; `/legacy` is retained for
e2e tests only. Talk-track lines reuse copy already on screen, so nothing here
needs to be memorized verbatim.

## 0. Pre-flight (≈1 min before the call)

1. `./bridge-ui/start-demo.sh` → wait for `Demo: http://localhost:3002`.
2. Open http://localhost:3002 and confirm the header shows **BFF online**
   (green dot). Offline default backend is the deterministic `FakeBackend` — no
   real LLM, no real data; that is intentional and honest for a demo.
3. Optional but recommended: `python bridge-ui/scripts/seed-demo.py` so the
   Dashboard/Audit/Observability tabs open populated instead of empty.
4. If the **How Bridge works — in 4 steps** guide is not showing (a previous
   demo may have dismissed it), click **? Tour** in the top bar — it restores
   the guide. (It persists dismissal under `localStorage: bridge:goldenPathHidden`.)

## 1. The story (Operate → Govern → Monitor)

### Minute 1–2 — Ask (Dashboard → the golden-path guide)

- Land on **Dashboard**. Point at the 4-step rail: **Ask → Decide → See → Prove**.
- Click **▶ Run a sample question**. It sends a cloned-card fraud report through
  the live pipeline and jumps to the Audit log, filtered to whatever the guard
  actually decided (on the fake backend this is a deterministic escalate).
  - Talk track: "A customer reports fraud. Watch what the system does when it
    isn't sure."

### Minute 2–4 — Decide (Flow)

- Go to **Flow**. Click the chip **"My card was cloned — there are purchases I
  don't recognize"** and press Inspect.
- Walk the **pipeline trace**: PII masking, intent, RAG grounding, then the
  **uncertainty guard**. Land on the decision badge + the plain-language
  explanation beneath it.
  - Talk track (reuse the on-screen `DECISION_EXPLAIN` text): "It abstained and
    escalated rather than guess — the wedge: a customer-facing LLM that stops
    when unsure."
- Click **See this decision in the audit trail →** on the result card — every
  answer becomes a logged, verifiable record.

### Minute 4–7 — Prove (Audit)

- In **Audit**, click **Verify chain** (and **Verify from disk**) — the
  hash-chained trail recomputes clean.
- Click **🔬 Prove tamper detection** — the aha moment: the chain is shown
  intact, an entry is mutated in memory, the chain **catches** it, then it's
  restored. Nothing is silently editable.
  - Talk track: "This is what 'tamper-evident audit' actually means — not a
    promise, a proof you just watched."

### Minute 7–9 — Govern (Governance)

- Go to **Governance**. The **Regulatory coverage & evidence package** panel is
  open by default: the SR 11-7 crosswalk + the **signed evidence package**.
- Click **Export package (.json)** (signed) and open **Download PDF (2-page)**
  → `/evidence-report` — the CRO leave-behind to forward to Risk.
- Scroll to **Governed Changes**: propose → approve → apply needs three
  different operators (two-person control / four-eyes, SR 11-7).

### Minute 9–10 — Close

- One line: "Every answer is a governed decision with a signed, tamper-evident
  record your model-risk team can file — not just an answer."

## Recovery (if something breaks mid-demo)

- **Header goes red / BFF offline:** `start-demo.sh` auto-restarts the backend;
  wait a few seconds for **BFF online**. If it doesn't recover, re-run
  `./bridge-ui/start-demo.sh` (it cleans stale processes).
- **A free-typed question comes back RE-ASK instead of answered:** that's the
  guard working, not a bug — quote the on-screen explanation.
- **Backend truly down:** every panel shows one offline banner with the restart
  command; no data means "not measured", not "zero".

## Scope honesty

Keep [`DEMO_SCOPE.md`](DEMO_SCOPE.md) open in a tab — it pre-empts "why doesn't
it do X?" with the honest, documented limits. This is a single-tenant
pre-release demonstrator (see [`../../SECURITY.md`](../../SECURITY.md)): no SOC 2,
no hosted SaaS, no reference customer.

> This runbook is the doc complement of the in-product guided rail (planning/33
> quick-win #5). If that rail changes, update the click path here.
