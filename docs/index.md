# llm-uncertainty-banking

**Turn LLM uncertainty into auditor-ready regulatory evidence** — a governed
decision you can defend to a model-risk (MRM) reviewer, not just an answer.

`llm-uncertainty-banking` (import name: `lub`) is an open-source Python
library that wraps LLM backends, estimates answer-level uncertainty using
published research methods, measures calibration, and renders NIST AI Risk
Management Framework reports suitable for model-risk review at regulated
financial institutions.

## Why

In banking, an LLM answer is only useful if you know when to trust it.
This library brings together the building blocks that model-risk teams
need to evaluate and document LLM behavior:

- **Backends** — HuggingFace, OpenAI, Anthropic, vLLM, plus a
  deterministic `DummyBackend` for hermetic tests.
- **Uncertainty estimators** — token log-probability, self-consistency,
  semantic entropy, split conformal prediction, Monte Carlo dropout.
- **Calibration metrics** — ECE, Brier score, refusal AUROC, reliability
  diagrams.
- **Regulated-domain benchmarks** — FinQA, ConvFinQA, TAT-QA, plus a
  hand-crafted Brazilian regulatory QA set (BCB Resolution 4.658, Basel III).
- **AI RMF reports** — markdown / HTML reports mapping metrics to NIST AI
  RMF Govern / Map / Measure / Manage sub-categories.

## Quickstart

```python
from lub.pipeline import UncertaintyPipeline

pipe = UncertaintyPipeline.from_pretrained(
    model="dummy-model",
    backend="dummy",
    estimator="self_consistency",
    n_samples=8,
)

result = pipe.answer("What is the Basel III minimum CET1 ratio?")
print(result.answer, result.confidence, result.should_refuse)
```

See [Getting Started](getting-started.md) for install instructions and a
tour of the CLI.

## Documentation map

Narrative docs:

- [Getting Started](getting-started.md) — install, first run, CLI tour.
- [Architecture](architecture.md) — the five-layer import contract + governance runtime.
- [Estimators](estimators.md) — the 22 uncertainty estimators, how to pick one.
- [Benchmarks](benchmarks.md) — FinQA, ConvFinQA, TAT-QA, plus the Brazilian regulatory QA set.
- [Governance](governance.md) — rails, policies, AI-RMF MANAGE sub-categories.
- [AI RMF mapping](airmf-mapping.md) — metric → NIST AI RMF sub-category crosswalk.
- [API reference](api/index.md) — auto-generated module docs.

Supporting folders (each has its own README):

- [`diagrams/`](diagrams/README.md) — Eraser.io source files for every diagram the tech report, README, and petition evidence cite.
- [`prompts/`](prompts/README.md) — copy-paste LLM prompts for landscape scans, open-ended review, and market research.
- [`sweeps/`](sweeps/README.md) — in-repo mirrors of competitive sweeps (mirrors of the operator-side `market_research/`).
- [`tech-report/artifacts/`](tech-report/artifacts/README.md) — generated evaluation outputs (JSON records, reliability diagrams, OSCAL exports) across DummyBackend / distilgpt2 / Qwen2.5-0.5B variants.
