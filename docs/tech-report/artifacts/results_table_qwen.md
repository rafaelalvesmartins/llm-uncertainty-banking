<!--
================================================================================
⚠️  WARNING — "CANONICAL" SLOT, BUT NOT YET FIT FOR CITATION (2026-04-25)  ⚠️

This file is the slot designated by `README.md` in this folder as
"canonical for citable quantitative claims" (USCIS / arXiv / recommenders).
Right now it does NOT meet that bar:

  1. Only 4 of the 22 estimators have been run (token_logprob, perplexity,
     token_sar, self_consistency). The other 18 are missing.
  2. All 4 rows show Accuracy = 0.000 and AUROC = 0.500. Qwen2.5-0.5B is
     too small to answer FinQA-class extractive questions correctly, OR
     the answer-extraction template is failing.

A reviewer / adjudicator who lands on this table will see "the model gets
0% correct and AUROC = 0.500 (random)" and (correctly) conclude the
artifact is not evidence of working uncertainty estimation.

Tracked as P0 item #1 in `06_Projeto_GitHub/AUDIT_2026-04-25.md`.
Resolution path (one of):
  (a) re-run on Qwen2.5-7B or Llama-3-8B over the full 22-estimator sweep,
  (b) pivot the headline benchmark to BR-Regulatory binary yes/no
      (the small model can score above chance there) and add a separate
      "scaling sweep" table on a larger model,
  (c) freeze the current 22-estimator dummy/distilgpt2 sweep as
      "calibration-metrics demonstration" only and add a one-row real-task
      result on a larger hosted model (e.g. Claude Haiku via Anthropic
      backend) so at least one cell shows non-trivial accuracy.

DO NOT submit to arXiv, USCIS, or recommenders until this file is
regenerated and at least one row shows non-trivial Accuracy and a
non-0.500 AUROC.

See `README.md` in this folder for the canonical "do not cite" rule.
================================================================================
-->

> **⚠ 4-of-22 estimators run; all Acc = 0.000 / AUROC = 0.500 — NOT YET FIT FOR CITATION.** See header.

| Estimator | Model | Acc | ECE | AUROC | PRR | Brier | RMSCE |
|-----------|-------|-----|-----|-------|-----|-------|-------|
| token_logprob | Qwen2.5-0.5B | 0.000 | 0.6748 | 0.500 | 0.000 | 0.4582 | 0.6767 |
| perplexity | Qwen2.5-0.5B | 0.000 | 0.6748 | 0.500 | 0.000 | 0.4582 | 0.6767 |
| token_sar | Qwen2.5-0.5B | 0.000 | 0.3420 | 0.500 | 0.000 | 0.1224 | 0.3495 |
| self_consistency | Qwen2.5-0.5B | 0.000 | 0.3333 | 0.500 | 0.000 | 0.1111 | 0.3333 |