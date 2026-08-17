<!--
================================================================================
⚠️  WARNING — NOT FIT FOR EXTERNAL CITATION (2026-04-25 audit)  ⚠️
This `_real` variant runs on `distilgpt2` (82M params, no instruction
tuning). All rows show Accuracy = 0.000 and AUROC = 0.500 because the model
is too small for FinQA-class extractive QA — it never produces the gold
answer string and the refusal-AUROC defaults to chance.

The calibration metrics (ECE / Brier / RMSCE) are still well-defined — you
can be perfectly miscalibrated about garbage — but no reviewer will read
"Accuracy = 0.000" as evidence of working uncertainty estimation.

Status: do NOT cite this file in arXiv, USCIS petitions, recommender
outreach, the tech-report draft §5, or any other external surface.

Tracked as P0 item #1 in `06_Projeto_GitHub/AUDIT_2026-04-25.md`.
Resolution path:
  (a) re-run on Qwen2.5-7B or Llama-3-8B (~1 GPU-day or ~$100–$300 hosted),
  (b) or pivot the headline benchmark to BR-Regulatory binary yes/no
      (the small model can hit non-trivial accuracy there).

See `README.md` in this folder for the canonical "do not cite" rule.
================================================================================
-->

> **⚠ All Acc = 0.000 / AUROC = 0.500 — NOT FIT FOR CITATION.** See header.

| Estimator | Model | Accuracy | ECE | AUROC | PRR | Brier | RMSCE |
|-----------|-------|----------|-----|-------|-----|-------|-------|
| token_logprob | distilgpt2 | 0.000 | 0.9637 | 0.500 | 0.000 | 0.9293 | 0.9639 |
| perplexity | distilgpt2 | 0.000 | 0.9637 | 0.500 | 0.000 | 0.9293 | 0.9639 |
| token_sar | distilgpt2 | 0.000 | 0.6688 | 0.500 | 0.000 | 0.4705 | 0.6858 |
| self_consistency | distilgpt2 | 0.000 | 0.5167 | 0.500 | 0.000 | 0.3389 | 0.5821 |