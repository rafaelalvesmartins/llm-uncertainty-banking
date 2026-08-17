# Competitor / Adjacent-Project Review Prompt

Copy-paste the prompt below into any LLM session. Replace `{{REPO_URL}}`
with the GitHub URL of the project you want to audit. The output is a
structured report you can act on directly.

---

## Prompt

```
You are a senior ML engineer reviewing an open-source project to extract
ideas for a competing library called `llm-uncertainty-banking` (LUB).

## Target project

Clone or inspect: {{REPO_URL}}

## Context about LUB (so you can judge relevance)

LUB is a Python library (Apache-2.0) for uncertainty quantification +
calibration + NIST AI RMF reporting for LLMs in regulated banking.

Architecture — 5 strict layers enforced by import-linter:
  L1 Wrappers    — HF, OpenAI, Anthropic, vLLM, Dummy, + LMPolygraph adapter
  L2 Uncertainty — token_logprob, perplexity, self_consistency,
                   semantic_entropy, conformal, mc_dropout, p_true,
                   eigenscore, verbalized_1s/2s, lmpolygraph (~60 methods)
  L3 Calibration — ECE, Brier, refusal AUROC, PRR, risk-coverage curve,
                   sharpness, miscalibration area, missing ratio,
                   5 sklearn-style Normalizers (Identity/MinMax/BinnedPCC/
                   Isotonic/Quantile) with JSON persistence, matplotlib plots
  L4 Benchmarks  — FinQA, ConvFinQA, TAT-QA, Brazilian regulatory QA (20
                   hand-crafted questions from BCB/BIS public docs), runner
  L5 Reports     — Jinja2 AI RMF markdown/HTML template, metric-to-NIST
                   sub-category mapping, renderer with base64 PNG embedding

Cross-cutting orchestration (above the layers):
  pipeline.py  — UncertaintyPipeline facade with registry + from_pretrained
  cli.py       — typer CLI: answer / benchmark / report / repro / version
  rails.py     — input/output guard hooks (PII, max-length, confidence floor)
  guard.py     — Guardrails-AI-inspired uncertainty gate
  policies.py  — PolicyDecision enum (ABSTAIN/FLAG/PASSTHROUGH/RAISE) mapped
                 to NIST AI RMF MANAGE sub-categories

State: 179 tests passing, mypy strict on 42 source files, 2 import-linter
contracts kept. Positioned as "last-mile compliance overlay" for banking.

## What I need from you

Produce a structured report with these sections:

### 1. Repo at a glance
License, stars/forks, last commit, LOC by directory, primary modules, entry
points. Note if abandoned or very active.

### 2. Features they have that LUB lacks
Name each one, give the file path, cite the paper if any. Skip features LUB
already has (check my list above carefully).

### 3. Architectural patterns worth adopting
How do they register components, handle the backend abstraction, test
stochastic methods, cache expensive operations, structure their CLI/config?
Be specific with file paths and line numbers.

### 4. Benchmark / dataset harness
Do they have something like LUB's BenchmarkRunner? How does it differ?
Anything LUB should adopt?

### 5. Visualization / reporting
Do they produce reports, dashboards, or plots? What format? LUB already has
AI RMF markdown/HTML reports — note only things LUB can learn from.

### 6. Python packaging and dev ergonomics
pyproject layout, test fixtures, CI, docs. Anything notably better or worse
than LUB's setup.

### 7. Integration feasibility
Could LUB realistically wrap this project as an adapter (like we did with
LM-Polygraph)? What's the public API surface? Is it stable?

### 8. Top 5 prioritized recommendations
Concrete, actionable items ranked by impact-to-effort. For each:
- What to do
- Where it goes in LUB's layer structure (L1-L5 or cross-cutting)
- Rough effort estimate in hours
- Why it matters for LUB's "regulated banking compliance overlay" positioning

## Constraints

- Do NOT copy code — LUB will re-implement ideas under its own copyright
- Note the target project's license so I know what's permissible
- If the repo is abandoned or has <50 stars, flag that early — different
  threat level than an active project
- Keep the report under 1500 words. Dense and specific beats exhaustive.
```

---

## Suggested targets

Projects worth reviewing with this prompt (from the SWOT and competitor
sweep):

| Project | URL | Why |
|---------|-----|-----|
| LM-Polygraph | github.com/IINemo/lm-polygraph | **Done** — 2026-04-15 session |
| Guardrails AI | github.com/guardrails-ai/guardrails | Input/output validation, structural guarantees, rail patterns |
| NeMo Guardrails | github.com/NVIDIA/NeMo-Guardrails | Programmable rails, Colang DSL, dialogue-level safety |
| IBM AIF360 | github.com/Trusted-AI/AIF360 | Classical ML fairness/bias metrics — could LUB port any to LLM UQ? |
| Uncertainty Toolbox | github.com/uncertainty-toolbox/uncertainty-toolbox | Pure calibration metrics library — compare API surface with LUB L3 |
| semantic_uncertainty | github.com/jlko/semantic_uncertainty | Kuhn et al. reference implementation — compare with LUB's semantic_entropy |
| Credo AI Lens | github.com/credo-ai/credoai_lens | Deprecated but had governance reporting — any patterns to salvage? |
| PIXIU / FLARE | github.com/The-FinAI/PIXIU | Financial LLM benchmark suite — dataset loaders and evaluation patterns |
| Holistic AI | github.com/holistic-ai | Classical ML governance — pivot signals toward LLM-native? |
| AI Verify | github.com/aiverify-foundation/aiverify | Singapore AI governance toolkit — reporting patterns |
