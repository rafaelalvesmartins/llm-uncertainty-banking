# LUB + Bridge — Project Validation Brief

**Audience:** an LLM (or human) asked to independently validate the project's claims by reading the source.
**Scope:** the `06_Projeto_GitHub/llm-uncertainty-banking/` repository, including the `src/lub/` library and the `bridge-ui/` demo (FastAPI BFF + Next.js dashboard).
**Snapshot date:** 2026-05-18. File line numbers may drift; commit hashes are stable.
**Filing context:** this codebase is the technical exhibit for an EB-2 NIW immigration petition with filing target 2026-07-01.

> Every concrete claim below is paired with a file path (and a line number or grep pattern when meaningful). Verify by reading. The **validation checklist** at the end of this document lists every claim a reviewer should re-check.

---

## 1. Executive summary

The repository contains two coupled artifacts:

**LUB (`src/lub/`)** — a Python library for *uncertainty quantification and calibration on top of LLM/banking pipelines*. It exposes Estimators, Backends, a `UncertaintyGuard` that gates decisions on calibrated confidence, conformal-prediction variants, compliance-framework mappings (SR 11-7, BCB 4893, ISO 42001), and benchmark / report infrastructure. Library code, version-controlled, ~150 modules.

**Bridge demo (`bridge-ui/`)** — a FastAPI BFF (`server.py`, 3832 lines) backed by a 12-stage banking-AI pipeline that orchestrates LUB's primitives, plus a Next.js 14 frontend (App Router, TypeScript) that renders the pipeline live. The BFF can run against a deterministic `FakeBackend` (no API key, no network) OR against `ollama:llama3.1:8b` running locally. **The demo is what a USCIS reviewer can see end-to-end** — it's the central Prong-2 exhibit.

The project has been **validator-driven hardened across 11 rounds** (see `bridge-ui/docs/VALIDATION_HISTORY.md`). Each round = independent attack/edge-case report → remediation commit. Current state:
- 3596 unit tests collected, **753 tests passing** in the bridge subtree alone (696 unit + 57 safety smoke).
- 14-category safety classifier covering crisis, AML, discrimination, prompt-injection, etc.
- 27 BFF endpoints, 17 frontend API proxy routes.
- 21 DQ rules with per-rule customer-facing messages citing specific regulations.

## 2. Repository layout (key paths)

```
06_Projeto_GitHub/llm-uncertainty-banking/
├── src/lub/                              # The library
│   ├── connectors/bridge/                # 28-module bridge platform
│   │   ├── data_quality.py    (806 LOC)  # Input/output DQ rules
│   │   ├── data_governance.py (311 LOC)  # PII detection + masking + classification
│   │   ├── handoffs.py                   # Swarm-style agent handoff protocol
│   │   ├── memory.py                     # SemanticCache (bounded)
│   │   ├── customer_memory.py            # Letta-style per-customer blocks
│   │   ├── rag.py                        # InMemoryDocumentStore + TFIDFRetriever
│   │   ├── complexity.py                 # ComplexityRouter (SIMPLE/COMPLEX/REGULATORY)
│   │   ├── audit.py                      # Append-only audit ledger
│   │   └── ... (governance, ab_testing, analytics, rate_limiter, etc.)
│   ├── calibration/                      # Conformal, Mahalanobis, MC dropout estimators
│   ├── compliance/frameworks/            # SR 11-7, BCB 4893, ISO 42001 control catalogs
│   ├── guard.py                          # UncertaintyGuard (PASSTHROUGH/FLAG/REASK/ESCALATE)
│   ├── wrappers/                         # Model backend wrappers (dummy, azure_openai, ollama)
│   └── benchmarks/                       # Bench harness + answer scorer
│
├── bridge-ui/                            # The demo
│   ├── README.md                         # How to run
│   ├── docs/                             # Documentation index
│   │   ├── DEMO_SCOPE.md                 # What the demo intentionally does NOT do
│   │   ├── PETITION_EXHIBIT_GUIDE.md     # Prong-2 claim → evidence map
│   │   └── VALIDATION_HISTORY.md        # Round-by-round validation log
│   ├── backend/
│   │   ├── server.py            (3832 LOC) # FastAPI BFF + 12-stage pipeline + safety classifier
│   │   ├── test_safety_smoke.py (485 LOC)  # 57 regression cases pinning the safety contract
│   │   └── scripts/
│   │       └── generate_petition_exhibit.sh # Reproducible canonical demo session
│   └── frontend/                         # Next.js 14 (App Router, TypeScript)
│       ├── app/
│       │   ├── page.tsx                  # Main dashboard
│       │   ├── layout.tsx
│       │   └── api/                      # 17 proxy folders, 24 route.ts files
│       └── components/                   # Compliance, DriftPanel, InfoPanels, IntentsPanel,
│                                         #   Metrics, Pipeline, QueryPanel
│
├── tests/
│   ├── unit/connectors/bridge/           # Includes test_data_quality.py + test_data_governance.py
│   └── integration/                      # E2E flows, mark=integration
│
├── docs/tech-report/                     # arXiv-bound technical report
└── planning/                             # ADR-002, CANONICAL_FACTS, action plans
```

## 3. LUB library — what it does and why it exists

LUB ("LLM uncertainty banking") is designed to make calibrated-uncertainty practical at the application boundary of a banking LLM system. The thesis: regulators (BCB, BACEN, SR 11-7 reviewers) cannot accept "the model said so" — they need a defensible numeric on every decision plus a paper trail.

Core primitives:

| Module | What it does | Where |
|---|---|---|
| `Estimator` (abstract) | Returns calibrated confidence on an LLM answer | `src/lub/uncertainty/base.py` |
| `ConformalEstimator` family | Split, Adaptive, Mondrian, ConformalSampling variants | `src/lub/uncertainty/conformal*.py` |
| `MahalanobisEstimator` | Embedding-distance OOD detection | `src/lub/uncertainty/mahalanobis.py` |
| `UncertaintyGuard` | PASSTHROUGH/FLAG/REASK/ESCALATE decision on a calibrated answer | `src/lub/guard.py` |
| `ModelBackend` (abstract) | Wraps any LLM (azure_openai, ollama, fake) for hermetic testing | `src/lub/wrappers/base.py` |
| `Pipeline` | Orchestrator: backend → estimator → guard, plus audit hooks | `src/lub/pipeline.py` |
| SR 11-7 framework | 21-control coverage table the demo BFF surfaces | `src/lub/compliance/frameworks/sr_11_7.py` |

The Bridge platform (`src/lub/connectors/bridge/`) is a *concrete deployment* of LUB targeted at a Brazilian retail bank — it adds banking-specific intent classification, PT-BR PII regexes, BCB/COAF/LGPD compliance citations, and the multi-agent handoff layer.

## 4. Bridge demo — architecture

```
Browser ──→ Next.js (port 3000) ──→ /app/api/* ──→ FastAPI BFF (port 8000) ──→ lub.connectors.bridge
                                    (proxy routes)
```

**Frontend (Next.js 14, App Router):** dashboard at `bridge-ui/frontend/app/page.tsx`. 8 components in `bridge-ui/frontend/components/`. 17 API proxy folders that forward to the BFF on port 8000 (configurable via `BRIDGE_API_URL` env).

**Backend (FastAPI):** `bridge-ui/backend/server.py`. Single-file BFF (3832 lines). Hosts the 12-stage pipeline orchestrator, the safety classifier, the audit chain, and the `_RESPONSES` canned-answer table. Imports primitives from `lub.connectors.bridge.*` for DQ, DG, memory, RAG, complexity, handoffs.

**Two backend modes:**
- `FakeBackend` (default) — canned responses by intent keyword. No API key, no network. Used for deterministic exhibit + most validator rounds.
- `ollama:llama3.1:8b` — real local LLM. Activated when `OLLAMA_HOST` env points to a running ollama server. The `/health` endpoint reports `backend_is_real: true` and the frontend swaps the "DEMO MODE" banner for "LIVE LLM".

**27 BFF endpoints** (verify with `grep -c "^@app\." bridge-ui/backend/server.py`):
```
GET  /health                          GET  /audit
GET  /version                         DELETE /audit
POST /query                           GET  /explain/{audit_index}
GET  /metrics                         POST /feedback
GET  /queue/depth                     GET  /feedback
GET  /agents                          POST /handoff
GET  /cache                           GET  /handoff
DELETE /cache                         GET  /customers
GET  /docs/corpus                     GET  /customers/{customer_id}
GET  /dq-dg                           GET  /compliance/sr-11-7
(plus drift, intents, audit/verify, audit/explain, etc.)
```

## 5. The 12-stage pipeline

`POST /query` walks each request through this sequence. Each stage emits a `PipelineStage` record the frontend renders as a colored tile. Verify the names with `grep -oE 'name="[a-z_]+"' bridge-ui/backend/server.py | sort -u` (should return exactly these 12).

| # | Stage | Responsibility | Can short-circuit? |
|---|---|---|---|
| 0 | `rate_limit` | Token-bucket per-customer; returns `[Rate limit exceeded]` | Yes (ESCALATE) |
| 0a | `dq_input` | 21 input rules: prompt injection, SQLi, HTML/JS, credentials, empty/too-long, plus 7 banking-compliance rules (minor, AML cash, structuring, money mule, social-eng, phishing, cross-customer) | Yes (BLOCK → ESCALATE with per-rule customer_message) |
| 0b | `data_governance` | PII detect (CPF/CNPJ/email/account/card/phone/CREDENTIAL), classify (PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED), mask in place | Never (just transforms) |
| 1 | `semantic_cache` | Bounded cache (max 200, max age 300s) on cosine-sim of TF-IDF embeddings | Yes (HIT returns cached response, latency drops) |
| 2 | `complexity_router` | Picks tier (SIMPLE $0.05c / COMPLEX $0.30c / REGULATORY $1.50c) | Never (sets tier metadata) |
| 3 | `customer_memory` | Loads persona + preferences + risk_profile blocks (Letta-style) | Never |
| 4 | `rag_retrieval` | TF-IDF over `InMemoryDocumentStore` (BCB Manual PIX, IOF decree, etc.). top_k=2, min_score=0.05 | Never (just provides citations) |
| 5 | `intent_classifier` | `classify_intent(query)` — 14 safety intents take priority, then keyword-based banking intent | Never (returns label + confidence) |
| 6 | `agent` (chatbot/smart_payments/call_center via handoffs) | Each agent's `handle()` returns either reply text or another agent instance to hand off to | Never |
| 6b | `dq_output` | 4 rules: blocks hallucinated R$ amounts over PIX limits, refusal-shaped answers, etc. | Yes (suppress answer) |
| 7 | `uncertainty_guard` | `apply_guard(confidence, intent)` → PASSTHROUGH/FLAG/REASK/ESCALATE. Safety intents always ESCALATE regardless of confidence | Never (sets decision) |
| 8 | `cache_store` | Writes successful response back into semantic_cache | Never |
| 9 | `audit_trail` | Appends entry to bounded `_AUDIT: deque[dict] = deque(maxlen=2000)`. PII fields use the masked form from stage 0b, not the raw query | Never |

## 6. Safety classifier — 14 categories

The classifier lives in `bridge-ui/backend/server.py` (NOT in `lub/connectors/bridge/safety.py` — there's no such module as of this brief). Each category is wired in **7 places** (round-14 added the 7th — `_INTENT_CATALOG` — which powers `/intents`, `IntentsPanel.tsx`, and tooltip metadata in `Metrics.tsx`); violating the sync is the project's known structural risk. The 7 spots:

1. **Marker tuple or regex** at module top (e.g. `_CRISIS_MARKERS`, `_AML_VALUE_PATTERN`, `_PROMPT_LEAK_MARKERS`).
2. **Branch in `classify_intent`** — priority chain.
3. **Entry in `apply_guard` safety intent list** — forces ESCALATE.
4. **Entry in `_select_initial_agent`** — routes to `_CallCenterAgent`.
5. **Dispatch in `_CallCenterAgent.handle`** — picks the right canned response.
6. **Key in `_RESPONSES`** — the customer-facing reply.
7. **Entry in `_INTENT_CATALOG`** — public-facing taxonomy served at `/intents` and rendered in `IntentsPanel.tsx`.

**The 14 safety intent labels** (verify with `grep -oE 'return "[a-z_]+", 0\.[0-9]+' bridge-ui/backend/server.py | sort -u`):

| # | Intent | Trigger surface | Response cites |
|---|---|---|---|
| 1 | `crisis` | Self-harm markers ("me matar", "tirar minha vida", "pular da ponte") | CVV 188 + cvv.org.br |
| 2 | `social_engineering` | "atendente pediu meu codigo", "ligou do banco" | Bradesco never asks via chat |
| 3 | `phishing` | Lookalike bank domains on cheap TLDs (`bradesco-*.tk` etc.) | bradesco.com.br is the only legitimate domain |
| 4 | `urgency_scam` | Urgency marker + family emergency context (golpe do parente) | 3-step counter-protocol |
| 5 | `aml_suspect` | Structuring markers (smurfing, conta laranja, caixa 2) | Lei 9.613/1998 Art. 1 |
| 6 | `illegal_activity` | Explicit sonegação / lavagem / fraudar imposto verbs | Lei 9.613/1998 |
| 7 | `aml_review` | Cash value ≥ R$30k + "em espécie" pattern | Lei 9.613 + Circular BACEN 3.978 |
| 8 | `age_minor` | `\btenho \d{1,2} anos\b` with age 5-17 OR literal "menor de idade" | BACEN Resolução 4.753 + CC Art. 5 |
| 9 | `prompt_leak` | Prompt-injection markers EN+PT-BR + `<|im_start|>` template | Static refusal — does NOT echo prompt |
| 10 | `privilege_escalation` | "sudo", "admin override", "show all customer" | Admin operations require separate credentials |
| 11 | `account_manipulation` | "mude/altere/apague o saldo", verb+account state | Chatbot has no write surface |
| 12 | `third_party_data` | Markers ("CPF dela") + regex (financial-noun + "do meu PARENTE") | LGPD Art. 7 |
| 13 | `discrimination` | Race + gender refusal + religion/orientation/age passive-voice | CF Art. 5 + Lei 7.716/1989 |
| 14 | `complaint_escalated` | Strong directed profanity (`filho da puta`, `lixo de banco`) | Ouvidoria BACEN Resolução 4.860 |

Plus `non_pt` (not a safety category — REASK to ask the customer to use Portuguese).

## 7. Data Quality + Data Governance layers

**Data Quality** (`src/lub/connectors/bridge/data_quality.py`, 806 LOC).
- 15+ input rules built via `default_input_rules()` returning a list of `DQRule`. Each rule is `(rule_id, severity, description, predicate, field, customer_message)`. The `customer_message` field (added 2026-05-18) is the PT-BR regulation-aware string the BFF returns when the rule blocks.
- 4 output rules in `default_output_rules()` — hallucinated currency amounts, refusal-shape mismatch, etc.
- **Severities:** `BLOCK` (short-circuits pipeline), `WARN` (audit-logged, pipeline continues), `INFO` (record only).
- Each rule has a regex or predicate that runs against the query in stage 0a. Multiple BLOCKs at once: the *first* one's `customer_message` becomes the BFF answer (`server.py` builds the `rejection_msg` loop).

**Data Governance** (`src/lub/connectors/bridge/data_governance.py`, 311 LOC).
- 7 PII types: `CPF, CNPJ, EMAIL, PHONE, ACCOUNT, CARD, PIX_KEY, CREDENTIAL` (verify with `grep "PIIType\." src/lub/connectors/bridge/data_governance.py`).
- Detection regex per type (`_PATTERN_CPF`, `_PATTERN_CARD`, etc.). The CREDENTIAL detector is split into two regexes: `_PATTERN_CREDENTIAL_KW` (keyword + greedy capture to end-of-line, 80-char cap) and `_PATTERN_CREDENTIAL_BLOB` (JWT, PEM, sk-*, AIza*, AKIA*, github_pat, ghp_). They are intentionally separate so the keyword regex doesn't swallow only the first segment of a dotted JWT.
- Classification: presence of any RESTRICTED PII (CPF, CARD, ACCOUNT, CNPJ, PIX_KEY, CREDENTIAL) marks the message as `DataClassification.RESTRICTED` and `safe_for_external_llm=False`.
- Masking: `mask()` replaces each detected fragment with `[[REDACTED]:<type>]`. The audit trail stores the masked version, **never the raw**.

## 8. Compliance posture

The demo cites specific Brazilian + international regulations in customer-facing rejections and in the SR 11-7 coverage table.

- **BCB 4893** (operational risk management at Brazilian banks) — cited in the audit trail design and in the daily-digest output.
- **BACEN Resolução 4.753** (account opening / KYC for minors) — cited in INPUT_MINOR_KYC customer_message.
- **BACEN Resolução 4.860** (Ouvidoria — banking ombudsman channel) — cited in `complaint_escalated` response.
- **Lei 9.613/1998** (anti-money-laundering) — cited in `aml_suspect`, `illegal_activity`, INPUT_STRUCTURING, INPUT_MONEY_MULE.
- **Circular BACEN 3.978** (PCD / lavagem reporting thresholds) — cited in `aml_review` and INPUT_AML_CASH_BYPASS.
- **Lei 7.716/1989** (racism / discrimination crime) — cited in `discrimination`.
- **LGPD Art. 7** (lawful basis for personal-data processing) — cited in `third_party_data` and INPUT_CROSS_CUSTOMER.
- **CF Art. 5** (constitutional equality) — cited in `discrimination`.
- **SR 11-7** (US Fed model risk management) — 21-control coverage table at `/compliance/sr-11-7`. As of 2026-05-18, 4 controls measured against real numbers (`ece`, `brier`, `accuracy`, `refusal_auroc`); 17 marked `status: synthetic` (placeholder) for honest disclosure.

## 9. Frontend dashboard

`bridge-ui/frontend/app/page.tsx` is the main route. It renders:
- Header pill that polls `/api/health` every 7s and flips between "DEMO MODE" (FakeBackend) and "LIVE LLM" (ollama) banners based on `health.backend_is_real`.
- `QueryPanel` (top-left) — channel selector + example queries + free-text input.
- `Pipeline` (top-right) — 12 stages with per-stage status/timing.
- `Metrics` (mid) — queries processed, resolution rate, decision mix, p50/p95/p99 latency.
- `InfoPanels` (mid) — Agents, Cache, Customers, Corpus, DQ, DG.
- `IntentsPanel` — 14 safety categories with their markers.
- `Compliance` (bottom) — SR 11-7 table with `status: real | synthetic | pending`.
- `DriftPanel` — distribution shift indicators (recent addition).

Each component fetches via the corresponding `/api/*` proxy route, which forwards to the BFF on port 8000.

## 10. Tests

- **Bridge unit suite** at `tests/unit/connectors/bridge/`: ~767 tests covering data_quality (input + output rules including the round-7+ credential cases), data_governance (PII detect/classify/mask, lineage), audit chain, compliance link, complexity router, customer memory, RAG, handoffs.
- **Safety smoke** at `bridge-ui/backend/test_safety_smoke.py`: 57 parametrized cases across 4 test classes — `TestSafetyClassifierEndToEnd` (each of 14 safety intents + polymorphic cases), `TestInnocentBaselinesNotEscalated` (negative cases), `TestResponsesDictCoverage` (structural — every named intent has a response + escalates), and `TestPromptLeakProtection` added round-14 (9 prompt-leak probes EN+PT+template, each asserting intent + ESCALATE + that the canned refusal contains none of the system-prompt tokens an attacker fishes for).
- **Live adversarial smoke** at `n8n_scripts/bridge-smoke.sh` (added round-16): runs 12 adversarial queries against `localhost:8000/query`, asserts each returns `decision=ESCALATE`, and verifies the audit hash chain. Complements the pytest suite by exercising the full pipeline (DQ → governance → cache → classifier → agent → guard → audit) end-to-end. Cron-eligible; pre-demo gate.
- **Pre-commit hook** at `.githooks/pre-commit` runs the smoke suite automatically whenever `server.py`, `test_safety_smoke.py`, `data_quality.py`, or `data_governance.py` are staged — blocks the commit on red.
- **Combined test run:** `pytest bridge-ui/backend/test_safety_smoke.py tests/unit/connectors/bridge/ -q` returns **824 passed** in ~2.7s as of 2026-05-20. Total collected across the whole lub repo: ~3596 (verify with `pytest tests/unit/ -q --collect-only | tail -2`).

## 11. Validation history

`bridge-ui/docs/VALIDATION_HISTORY.md` is the running log. 11 rounds executed between 2026-04 and 2026-05-18. Each round = independent attack-pack report → remediation commit. Highlights:

- **Round 1-2:** Original B1 (cartão clonado → fatura template), B2 (SQLi passed), B3 (channel enum). All fixed.
- **Round 5:** B-NEW-1 (raw PII in audit) fixed via DG-aware audit-trail entry.
- **Round 7:** Original safety set established (crisis, social_engineering, illegal_activity, aml_review, third_party_data, account_manipulation, privilege_escalation, discrimination).
- **Round 8:** v8 wave — phishing, urgency_scam, aml_suspect, age_minor categories added.
- **Round 9:** Live LLM switch (FakeBackend → ollama) exposed gaps the canned responses had masked. Tax-evasion paraphrase, possessive verbs, gender discrimination, CPF-with-relative all fixed.
- **Round 10:** Per-rule `customer_message` in DQ. AML cash + smurfing predicate widening. `complaint_escalated` intent.
- **Round 11:** Cross-customer multi-pattern detector + Metrics percentile polish + 5th scheduled task (`EB2NIW-freshness-alarm`) on the petition fleet side. `prompt_leak` intent (14th safety category).

## 12. Known limitations (honest disclosure)

- **FakeBackend** is deterministic by design. Outputs are not LLM-grounded. Switch to ollama for live-model posture; the audit trail and decision logic are identical, only stage 6 (agent) changes.
- **17 of 21 SR 11-7 controls** marked `status: synthetic` — placeholder numbers. Only `ece`, `brier`, `accuracy`, `refusal_auroc` have real measurements as of 2026-05-18. Real measurements require ground-truth datasets that are not in the repo.
- **No `/api/feedback` consumer yet.** Endpoint stores votes in a `deque(maxlen=500)` but no calibration loop reads it.
- **Safety classifier is bridge-only.** Lives in `bridge-ui/backend/server.py`, not in `lub/connectors/bridge/safety.py` (the latter does not exist). Means the safety taxonomy is not reusable as a library yet.
- **Audit trail is in-memory** (`deque(maxlen=2000)`). Production banking would persist to append-only storage; the demo intentionally does not.
- **Customer memory is in-process.** Restart clears it. The seeded `demo-customer` re-loads on startup.
- **n8n container** still hosts the bridge code-quality workflows but the petition fleet has migrated to Windows Task Scheduler — the n8n cron crashes on SSH-node fires. See repo-level `memory/eb2niw_n8n_layout.md` (outside this directory) for the workaround.

## 13. Validation checklist for the reviewing LLM

For each numbered claim below, the reviewer should **open the cited file and confirm** the claim. A `FAIL` on any item should be flagged with the actual finding.

### Repository structure
- [ ] `src/lub/` exists and contains at least: `connectors/`, `compliance/`, `guard.py`, `wrappers/`, `benchmarks/`, `calibration/`.
- [ ] `src/lub/connectors/bridge/` contains both `data_quality.py` and `data_governance.py`.
- [ ] `bridge-ui/backend/server.py` exists and is > 3000 lines (`wc -l`).
- [ ] `bridge-ui/backend/test_safety_smoke.py` exists and is > 400 lines.
- [ ] `bridge-ui/frontend/app/page.tsx` exists and imports at least 5 components from `@/components/`.

### Pipeline
- [ ] `grep -oE 'name="[a-z_]+"' bridge-ui/backend/server.py | sort -u` returns the 12 stage names listed in §5 of this brief.
- [ ] `grep -c "^@app\." bridge-ui/backend/server.py` returns at least 20 (claim is 27).

### Safety classifier
- [ ] `grep -oE 'return "[a-z_]+", 0\.[0-9]+' bridge-ui/backend/server.py | sort -u` returns at least 14 distinct intent labels including the ones in §6.
- [ ] `_RESPONSES` dict in `server.py` has an entry for every intent named in `classify_intent`. (TestResponsesDictCoverage.test_each_safety_intent_has_response asserts this.)
- [ ] `apply_guard` ESCALATEs every safety intent. (TestResponsesDictCoverage.test_each_safety_intent_escalates asserts this.)
- [ ] Each of the 14 safety responses references the regulation listed in the §6 table (open `server.py:55-220` and inspect the `_RESPONSES` strings).

### Data Quality
- [ ] `default_input_rules()` in `data_quality.py` returns >= 15 `DQRule` instances.
- [ ] Each BLOCK rule defined in §7 has a non-empty `customer_message` string.
- [ ] `customer_message` for INPUT_MINOR_KYC cites "BACEN Resolução 4.753" or "Resolucao 4.753".
- [ ] `customer_message` for INPUT_AML_CASH_BYPASS cites "Lei 9.613" or "Circular BACEN 3.978".
- [ ] `customer_message` for INPUT_CROSS_CUSTOMER cites "LGPD Art. 7".

### Data Governance
- [ ] `PIIType` enum in `data_governance.py` defines at least: CPF, CNPJ, EMAIL, PHONE, ACCOUNT, CARD, CREDENTIAL.
- [ ] `_PATTERN_CREDENTIAL_KW` and `_PATTERN_CREDENTIAL_BLOB` are two SEPARATE compiled regexes (not collapsed into one alternation).
- [ ] `DataGovernor.detect()` returns matches for "Bearer xyz123abc" (credential), "minha senha eh hunter2 quero saldo" (credential), "CPF 123.456.789-10" (cpf), and `eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOjEyMzR9.SflKxwRJSMeKKF2QT4f` (credential).
- [ ] `DataGovernor.mask()` replaces "123.456.789-10" with `[[REDACTED]:cpf]` and leaves "Quero ver meu saldo" unchanged.

### Tests
- [ ] `cd 06_Projeto_GitHub/llm-uncertainty-banking && pytest tests/unit/connectors/bridge/ -q` reports >= 760 passes, 0 failures (as of 2026-05-20).
- [ ] `cd 06_Projeto_GitHub/llm-uncertainty-banking && pytest bridge-ui/backend/test_safety_smoke.py -q` reports >= 57 passes, 0 failures.
- [ ] Combined: `pytest bridge-ui/backend/test_safety_smoke.py tests/unit/connectors/bridge/ -q` returns >= 820 passes (the per-brief snapshot was 824 on 2026-05-20).
- [ ] `_INTENT_CATALOG` in `server.py` is a list with at least 14 entries, each with `name`, `family`, `agent`, `default_decision` keys.

### Frontend
- [ ] `bridge-ui/frontend/app/api/` contains at least 15 subdirectories, each with a `route.ts`.
- [ ] `bridge-ui/frontend/app/page.tsx` calls `setInterval(check, 7000)` for the health polling (line ~30-50).
- [ ] `bridge-ui/frontend/components/IntentsPanel.tsx` exists.

### Compliance integration
- [ ] `/compliance/sr-11-7` endpoint exists (grep for `@app.get("/compliance/sr-11-7"`).
- [ ] At least 4 of the 21 SR 11-7 controls have `status: "real"` (not `synthetic` / `pending`).
- [ ] The `aml_review` response cites "Lei 9.613" or "BACEN 3.978".
- [ ] The `crisis` response cites "CVV 188" or "cvv.org.br".

### Things the reviewer should be skeptical of

A reviewer should explicitly check the following claims that are easy to overstate:

1. **"14 categories, 7-spot sync"** — this is a project rule, not an enforced invariant. Smoke tests catch most violations but not all. If a reviewer finds a category in `_RESPONSES` that is *not* in `classify_intent` (or vice versa), that's a real bug. Run `python -c "import server; from server import _RESPONSES, _INTENT_CATALOG, classify_intent; ..."` and compare across all 7 surfaces (markers, classify_intent, apply_guard, _select_initial_agent, _CallCenterAgent.handle, _RESPONSES, _INTENT_CATALOG).
2. **"21 SR 11-7 controls with 4 real measurements"** — verify by inspecting `/compliance/sr-11-7` JSON. Anything outside those 4 should be tagged `synthetic` honestly.
3. **"Audit trail never stores raw PII"** — the regression test is in `tests/unit/connectors/bridge/test_data_governance.py::TestCredentialDetection`. Try a new attack vector (e.g., a CPF in the middle of a long sentence with punctuation) and verify the masked output via `DataGovernor.mask()`.
4. **"3596 unit tests collected"** — run `pytest tests/unit/ --collect-only -q | tail -2`. If the number is significantly different, claim drift.
5. **"FakeBackend produces deterministic output"** — send the same query twice; first should MISS, second should HIT semantic_cache (sim=1.0, latency drops to <1ms).

### Things the reviewer SHOULD NOT do

- Do not run the demo against a real banking dataset. The `customer_id="demo-customer"` is the only valid identifier for `/query`.
- Do not commit anything to this branch — validate read-only.
- Do not infer real-world compliance certification from the SR 11-7 coverage panel alone. The panel demonstrates **awareness** of the framework, not **certified compliance**.

---

## How to run a verification session

```bash
# 1. Get to the repo root
cd 06_Projeto_GitHub/llm-uncertainty-banking

# 2. Run the structural checks
pytest tests/unit/connectors/bridge/ -q
pytest bridge-ui/backend/test_safety_smoke.py -q

# 3. Start the BFF for runtime checks
cd bridge-ui/backend
uvicorn server:app --port 8000   # NO --reload during validation

# 4. From a second shell, run the live adversarial smoke (12 attack
#    queries, each should ESCALATE; audit hash chain verified)
bash /c/code/eb2niw/n8n_scripts/bridge-smoke.sh

# 5. Capture the canonical session
cd 06_Projeto_GitHub/llm-uncertainty-banking
bash bridge-ui/backend/scripts/generate_petition_exhibit.sh

# 6. Inspect out/canonical_session/audit.json and confirm PII is masked.
```

A reviewing LLM with file-read tools should be able to validate the entire checklist above in one session. Anything ambiguous: flag the specific item and the actual finding.
