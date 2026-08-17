# Pricing — `lub` / Bridge

> **What this page is:** an honest, MRM/AI-Governance-facing map of what is
> **free and open-source today** versus what a commercial engagement would add.
> It is written to survive vendor diligence: where a thing is not yet built, it
> is marked **roadmap** or **planned**, not implied. Read
> [`docs/sr-11-7.md`](docs/sr-11-7.md) for the same scope-limit discipline
> applied to the regulatory claims.

## The one-paragraph version

The **core is free, Apache-2.0 open source** — the `lub` library, its CLI, the
22 uncertainty estimators, the calibration metrics, and the OSCAL Assessment
Results emit. You can `pip install` it, run it air-gapped (numpy + stdlib core,
no data egress with local backends), and re-run every number an auditor asks
about. **You never pay to validate a single model run.** What a paid engagement
adds is (a) a **support & assurance** wrapper an MRM function can put in a TPRM
file, and (b) **Bridge hosted**, whose flagship is **Continuous Effective
Challenge (CEC)** — automated, scheduled re-challenge of your models on a
nightly cadence instead of the once-a-year human validation cycle. All figures
below are **illustrative bands only** — every engagement is scoped and quoted;
**contact us**.

---

## The open-core line

### FREE — OSS core (Apache-2.0, built today)

Everything needed to produce and reproduce single-run model-risk evidence:

- **`lub` library + Typer CLI** (`lub answer | benchmark | report | repro`).
- **22 UQ estimators + 14 calibration metrics** — pure numpy, no sklearn/torch.
- **OSCAL Assessment Results + Component Definitions** pre-mapped to six
  regulatory regimes, ingestible by GRC platforms (Trestle, RegScale).
- **Single-run compliance reports** — markdown / HTML / OSCAL, with SR 11-7
  three-pillar cross-mapping.
- **Governance primitives** — `lub.guard` + `lub.policies` (calibrated
  refusal), `lub.governance` (policy-as-code), `lub.ledger` (append-only,
  replayable uncertainty ledger, stdlib SQLite).
- **Air-gap-runnable** — the calibration core is numpy + stdlib only; with a
  local backend there is **no data egress**.

This tier is genuinely free. If open source is all you need, you owe us nothing.

### PAID — what a commercial engagement adds

Two independently purchasable lines. Neither is required to use the OSS core.

#### (a) Support & Assurance — for your Third-Party Risk file

An MRM/TPRM function usually cannot put unsupported OSS into a critical control
path without a vendor wrapper. This tier supplies that wrapper:

| Item | Status today |
|---|---|
| Support **SLA** (response/patch windows) | **Planned** — no SLA exists yet; today the repo is community best-effort via `SECURITY.md`. |
| Security patching + coordinated disclosure | Best-effort today; **contractual patching is roadmap**. |
| **TPRM / vendor-diligence questionnaire pack** | Being assembled; portions available on request. |
| **SOC 2** report | **Roadmap.** No SOC 2 exists today, and none is implied. |
| Version-pinned, tested release channel + upgrade guidance | Available on engagement. |

> **Honest posture (read before diligence):** there is **no SOC 2, no
> independent penetration test, no incorporated legal entity, no hosted SaaS,
> no signed SLA, and no reference customer** at this time. Those are goals, not
> facts. Anything in this table marked *planned* / *roadmap* is exactly that.

#### (b) Bridge hosted — the operated platform

Bridge turns the library into an operated, multi-model service. Its flagship is
CEC.

| Item | Status today |
|---|---|
| **Multi-model register** (inventory of many LLMs/use-cases) | **Roadmap.** The current Bridge console is **single-tenant, auth-gated demo** scope — one register, `FakeBackend` default, no multi-tenancy. |
| **Ledger persistence** (durable, queryable evidence store) | Core `lub.ledger` (SQLite) is built; **managed/durable hosting is roadmap** (Postgres/Timescale). |
| **Continuous Effective Challenge (CEC)** | Battery **runs today** as `lub.challenge` (replay + reasoning-drift + meta-calibration) driven by an **external scheduler** (see `bridge-ui/scripts/scheduled/`). The **nightly, managed, alerting** form is the paid productization. |
| **Scheduled OSCAL exports** | Idempotent export endpoints exist; **managed scheduling + delivery is roadmap**. |

##### Why CEC is the flagship

SR 11-7 makes **effective challenge** — critical review by objective, informed
parties — the central principle of a model-risk program. In practice most
institutions perform that challenge on an **annual** validation cycle.

> **Competitors do effective challenge once a year. Bridge does it every
> night.** CEC replays aged predictions, measures reasoning drift and
> meta-calibration, and surfaces where a model is weakening *between* validation
> cycles — so an independent reviewer acts on a fresh signal, not a stale one.

**Scope limit (same as `docs/sr-11-7.md`):** CEC **produces the evidence a
challenger uses**; it does **not** perform the independent human review, supply
the validator, or substitute for the organizational independence SR 11-7
requires. It is *evidence for* effective challenge, not *compliance with* it.

---

## Illustrative bands

Anchored to the documented **$50K–$1M/yr** that US banks spend on model-risk
management software (operating range corroborated by public McKinsey and KPMG
model-risk-spend estimates). For
reference, closed incumbent ValidMind lists a base tier around **~$5K/yr** on
AWS Marketplace with enterprise pricing behind a sales call (secondary source —
verify current pricing before relying on it). Positioning is **"lub-powered,
your-GRC-presented."** These are **not quotes**; every engagement is scoped.

| Band | Fits | Roughly | What's included |
|---|---|---|---|
| **Community** | Small institutions / a first use-case | free OSS + light support | OSS core, docs, best-effort community support. **$0** for the software. |
| **Assurance** | Regional / mid-size MRM function | low five figures / yr *(illustrative)* | Support & Assurance line (a): SLA *(planned)*, security patching, TPRM pack. Sits well **below** the $50K floor of typical MRM spend. |
| **Bridge** | Institution running many LLM use-cases | scoped per model count / cadence *(illustrative)* | Hosted Bridge (b): multi-model register *(roadmap)*, durable ledger, **Continuous Effective Challenge**, scheduled OSCAL exports. Priced into the **$50K–$1M/yr** MRM-spend envelope, not on top of a per-seat GRC license. |

> All bands are **illustrative "contact us" ranges**, not committed figures.
> Numbers are directional against public MRM-spend evidence, not a rate card.

## At a glance

| Capability | OSS (free) | Assurance (paid) | Bridge (paid) |
|---|:--:|:--:|:--:|
| `lub` library + CLI | ✅ | ✅ | ✅ |
| 22 estimators + 14 calibration metrics | ✅ | ✅ | ✅ |
| OSCAL emit (single run) | ✅ | ✅ | ✅ |
| Single-run compliance reports | ✅ | ✅ | ✅ |
| Air-gap runnable / no data egress (local backend) | ✅ | ✅ | ✅ |
| Support **SLA** | ❌ | 🅿️ planned | 🅿️ planned |
| Contractual security patching | ❌ | ✅ | ✅ |
| TPRM questionnaire pack | ❌ | ✅ | ✅ |
| SOC 2 report | ❌ | 🅿️ roadmap | 🅿️ roadmap |
| Multi-model register | ❌ | ❌ | 🅿️ roadmap |
| Durable ledger persistence | self-host SQLite | self-host SQLite | ✅ managed |
| **Continuous Effective Challenge (nightly)** | battery + external cron | — | ✅ **flagship** |
| Scheduled OSCAL exports | idempotent endpoints | — | ✅ managed |

Legend: ✅ built today · 🅿️ planned/roadmap (not yet built) · ❌ not offered in
this tier.

---

## What we will not claim

To keep this document safe for both a bank's procurement team and its intended
audience:

- We do **not** claim a SOC 2, an independent penetration test, an incorporated
  legal entity, a signed SLA, a production hosted SaaS, or any reference
  customer. None exist yet.
- Pricing here is **illustrative** and anchored to public MRM-spend evidence;
  it is not a rate card and not a commitment.
- Regulatory anchors (SR 11-7 pillars, the six OSCAL regimes) are described in
  [`docs/sr-11-7.md`](docs/sr-11-7.md) and
  [`README.md`](README.md); where a citation is not already verified in-repo,
  **verify against the primary source** before relying on it.

**Contact us** to scope an engagement.
