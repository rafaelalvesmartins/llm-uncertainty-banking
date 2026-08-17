<!--
================================================================================
⚠️  WARNING — DO NOT CITE THIS FILE  ⚠️
This table is regenerated from `DummyBackend`, a deterministic stub used for
unit tests, CI, and tutorial-doc screenshots ONLY. The numbers below do not
correspond to any real model. Citing this file in arXiv, USCIS petitions,
recommender outreach, or any external publication is misrepresentation.

For citable quantitative claims:
  - prefer `results_table_qwen.md`  (Qwen2.5-0.5B, larger real model)
  - or     `results_table_real.md`  (distilgpt2, baseline real model)

NOTE (2026-04-25 audit): the `_qwen` and `_real` variants currently also show
Accuracy = 0.000 and AUROC = 0.500 across all rows because the underlying
model is too small to score correctly on FinQA-class extractive tasks (or
the answer-extraction is failing). Re-running benchmarks on a larger model
(Qwen2.5-7B / Llama-3-8B) — or pivoting to a task the small model can do
(e.g. binary BR-Regulatory yes/no) — is tracked as P0 item #1 in
`06_Projeto_GitHub/AUDIT_2026-04-25.md`. Until then, NONE of the three
variants is fit for external citation.

See `README.md` in this folder for the canonical "do not cite" rule.
================================================================================
-->

> **⚠ DummyBackend / synthetic only — NOT FOR CITATION.** See file header.

| Estimator | Backend | Accuracy | ECE | Refusal AUROC | PRR | Brier | AURC |
|-----------|---------|----------|-----|---------------|-----|-------|------|
| token_logprob | DummyBackend | 0.000 | 0.3679 | 0.500 | 0.000 | 0.1353 | 0.9500 |
| perplexity | DummyBackend | 0.000 | 0.3679 | 0.500 | 0.000 | 0.1353 | 0.9500 |
| self_consistency | DummyBackend | 0.000 | 0.1000 | 0.500 | 0.000 | 0.0100 | 0.9500 |
| p_true | DummyBackend | 0.000 | 0.5000 | 0.500 | 0.000 | 0.2500 | 0.9500 |
| token_sar | DummyBackend | 0.000 | 0.3679 | 0.500 | 0.000 | 0.1353 | 0.9500 |