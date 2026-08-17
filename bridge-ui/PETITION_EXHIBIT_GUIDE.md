# Bridge Banking AI — Petition Exhibit Guide

**Purpose.** This document tells a USCIS reviewer (and the petitioner's counsel) what the Bridge demo proves for the EB-2 NIW Prong-2 narrative, what evidence to capture from it for filing, and which artifacts already exist in the repository.

Filing target: **2026-07-01**. Demo last validated: round-11 (2026-05-18); **Governança tab + governance panels added 2026-06-10 — capture, then freeze (see "Governança tab" section below).**

---

## What the demo is

A 12-stage banking-AI pipeline that demonstrates uncertainty quantification (LUB), regulatory compliance posture (SR 11-7, BCB 4893, LGPD), and a defense-in-depth safety taxonomy in a customer-facing chat context. The demo runs end-to-end against either a `FakeBackend` (deterministic canned responses, no API key) or `ollama:llama3.1:8b` (real local LLM).

**Why this is petition-relevant.** Prong-2 asks whether the petitioner is *well-positioned* to advance an endeavor of national importance. Concrete demonstrators of regulated-AI design — with primary-source citations and a validator-driven hardening history — are stronger Prong-2 evidence than published papers alone, because they show the petitioner can ship the work, not just write about it.

## What the demo proves (mapped to Prong-2 claims)

| Prong-2 claim | What the demo shows | Where to capture evidence |
|---|---|---|
| Knowledge of banking compliance frameworks | `/compliance/sr-11-7` endpoint returns 21-control coverage table; DQ rule messages cite BACEN/COAF/Lei 9.613/LGPD by article number | Screenshot of `/compliance/sr-11-7` panel + audit log entry showing a regulation-citing DQ rejection |
| Practical implementation skill (not just theory) | 9000+ LOC, 753 passing tests, 16 commits in a single iteration day, validator-driven hardening across 11 rounds | `git log --oneline` since 2026-05-13; `VALIDATION_HISTORY.md`; `git shortlog -sn --use-mailmap` |
| Uncertainty quantification at the application boundary | `UncertaintyGuard` decision (PASSTHROUGH/FLAG/REASK/ESCALATE) visible on every query; confidence + reason exposed in audit | Pipeline trace screenshot for one canonical query of each decision class |
| Safety + PII discipline | 14-category safety classifier; CPF/CNPJ/card/email/credentials masked in audit; per-rule customer messages | `/audit` GET sample (post-mask), screenshot of `IntentsPanel`, the 14-category memory file |
| Honest reporting of model limits | DEMO_SCOPE.md enumerates what `FakeBackend` doesn't do; SR 11-7 metrics tagged `synthetic` when not measured against real data | `DEMO_SCOPE.md`, `/version` payload showing `backend_is_real: false` |
| Validator-driven hardening | 11 rounds of independent validation, each with a written report and a remediation commit | `VALIDATION_v9.md`, `VALIDATION_HISTORY.md`, the round-N commit messages |

## Governança tab — evidence added since round-11 (capture, then freeze)

Since the round-11 snapshot the demo gained a dedicated **Governança** tab that makes the lub framework's model-risk posture visible end-to-end. These panels are **Prong-2 corroboration** — they show, in a running system, the crosswalk and calibration the lub framework claims (Prong-1 §1.2 / Prong-2 §3.1). Frame every item as *the lub crosswalk/calibration rendered live*, **not** as "implementing" the frameworks (the Prong-1 draft holds the methodology-bridge line — do not break it).

| Panel | Endpoint | What it proves (Prong-2) | Maps to exhibits |
|---|---|---|---|
| **Cobertura Regulatória** | `GET /compliance/frameworks` | The lub crosswalk maps uncertainty metrics to **7 supervisory frameworks / 36 controls** across jurisdictions — rendered live, not asserted | E-02 (NIST AI RMF), E-03 (NIST 600-1), E-04 (SR 11-7), E-08 (EU AI Act); also BCB 4.893, BCBS 239, ISO 42001/23894 |
| **Conformidade SR 11-7** | `GET /compliance/sr-11-7` | 3-pillar SR 11-7 mapping (controls + metrics); calibration metrics graded pass/fail vs targets | E-04 |
| **Calibração** | `GET /calibration` | Real ECE / Brier / refusal-AUROC + reliability diagram (per-bin n and 95% CI) computed by `lub.calibration` over labelled samples — corroborates the "measures calibration error … 14 calibration metrics" claim | lub artifact; ties to D-04/D-05 (OSCAL / AI-RMF outputs) |
| **Model Card** | `GET /model-card` | SR 11-7 §III model-inventory record built from live version / prompt / corpus fingerprints | E-04 (SR 11-7 §III) |
| **Inventário de Frota** | `GET /fleet` | Portfolio/inventory view (owner, risk, lifecycle, ECE, cost). **Only the Bridge row is LIVE; the rest are MOCK siblings** illustrating perimeter-scale governance — capture with the MOCK flags visible so it is never read as a real multi-system deployment | illustrative; supports the "adoptable across the perimeter" Prong-1 §1.3 narrative |

**Capture note.** Screenshot the Governança tab and the panels above for the exhibit packet, then **freeze** (per the Cadence rule below — the demo is an exhibit, not an evolving product). Tag `petition-exhibit-2026-07-01` once captured.

**Do NOT** lean on these for Prong-1 national-importance: that prong is government-anchored (Group E) by design; industry framing / figures-on-a-screen read as *field* importance and weaken it (Prong-1 RFE scan #5).

## Evidence to capture for the filing

The exhibit packet should include at minimum:

### Screenshots (high-resolution PNG, mask any PII first)

1. **Header + DEMO MODE banner** showing `FakeBackend` declared. Establishes that no real banking data is involved.
2. **Pipeline trace** for the canonical query `"Quero ver meu saldo"` (PASSTHROUGH path, all 12 stages green, total latency).
3. **Pipeline trace** for `"Meu cartão 4111-1111-1111-1111 foi clonado"` (ESCALATE path — fraud intent + PII masked).
4. **Pipeline trace** for the credential leak case `"minha senha é XYZ123 quero saldo"` (DQ block, customer_message cites no-credentials-in-chat).
5. **Compliance panel** (`/compliance/sr-11-7`) showing the 21-control coverage table with `status: synthetic` on the pending rows.
6. **Audit panel** showing 8-10 entries with `classification: restricted` and `[[REDACTED]:cpf]`/`[[REDACTED]:card]` masks in place.
7. **Intents panel** showing the 14 safety categories with their markers and priority order.

### Code citations (link to GitHub commit hash, not branch tip)

- `src/lub/connectors/bridge/data_quality.py` — DQ rule definitions including the per-rule `customer_message` field added in commit `e24cec4`.
- `src/lub/connectors/bridge/data_governance.py` — PII detection + masking, including the `CREDENTIAL` type added in `d1d6a71`.
- `bridge-ui/backend/server.py` — 12-stage pipeline orchestrator + safety classifier (14 categories).
- `bridge-ui/backend/test_safety_smoke.py` — 57-case regression suite pinning the safety contract.

### Logs / artifacts (mask PII, then zip)

- One day of `/audit` GET output, after PII masking, showing the full chain of `query → intent → decision → response` for a real demo session.
- A `pytest` run summary (`bridge unit + safety smoke`) demonstrating 753 passing tests with timings.
- `VALIDATION_HISTORY.md` as the trail of rounds 1–11.

### Counsel-facing summary

`PETITION_FLEET_ANALYSIS_2026-05-18.md` is the petitioner's own honest assessment of which fleet components generate evidence value. Attach as appendix.

## What to NOT include

- The `bridge-ui/frontend/.next/` build cache. Generated, not source.
- Any local `.env` or `customer_id` of an actual person.
- Raw audit entries from before commit `4b5cf1f` — those predate the LGPD-compliant PII masking and contain raw CPFs.
- Any commit message that names a specific Bradesco employee, branch number, or internal URL.

## Generating the canonical demo session

A reproducible session — the same 12 queries every time, mascarando PII na saída, dump em `out/canonical_session/` — is the cheapest path to evidence that is consistent across re-runs. Script lives at `bridge-ui/backend/scripts/generate_petition_exhibit.sh` (canonical query list inline at the top of the script).

Run from the project root:

```bash
cd 06_Projeto_GitHub/llm-uncertainty-banking
bash bridge-ui/backend/scripts/generate_petition_exhibit.sh
```

Output: `out/canonical_session/{audit.json,metrics.json,pipeline_traces.json,version.json,intents.json,compliance.json}` plus a markdown index.

The script assumes the BFF is running locally on port 8000. Start it first with `uvicorn server:app --port 8000` (no `--reload` for evidence generation; see `README.md` Validation section).

## Cadence

This guide should be re-read **before each filing-window milestone**. The Bridge demo is an exhibit, not an evolving product, in the petition context — adding new features after the evidence is captured creates a moving target the reviewer cannot pin to a specific code version. Tag a `petition-exhibit-2026-07-01` git tag when the evidence is captured.

If the petition is denied and re-filed, this guide is the seed for the next exhibit refresh.
