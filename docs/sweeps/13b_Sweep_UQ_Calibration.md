# Sweep: UQ & Calibration — LM-Polygraph, Uncertainty Toolbox, ConformalLLM

Generated: 2026-04-16. Covers LUB's L2/L3 gaps.

---

## Repo 1: LM-Polygraph

### License: MIT — Compatible with Apache-2.0? Yes

### Methods LUB lacks

| Method | Paper | ~Lines | Requires |
|--------|-------|--------|----------|
| `MahalanobisDistanceSeq` | Lee et al. 2018 "Simple Unified Framework for OOD Detection" | ~80 | whitebox (embeddings + calibration set) |
| `RelativeMahalanobisDistanceSeq` | Ren et al. 2023 "Out-of-Distribution Detection with Deep Nearest Neighbors" | ~60 | whitebox (embeddings) |
| `RDESeq` (Relative Density Estimation) | Yoo et al. 2022 | ~70 | whitebox (embeddings) |
| `TokenSAR` / `SentenceSAR` / `SAR` | Duan et al. 2023 "Shifting Attention to Relevance" | ~120 total | whitebox (logprobs) |
| `RenyiNeg` (Rényi divergence) | Information theory, adapted by Polygraph | ~40 | whitebox (logprobs, n samples) |
| `FisherRao` (Fisher-Rao distance) | Rao 1945, adapted for LLM sequences | ~50 | whitebox (logprobs, n samples) |
| `SemanticDensity` | — | ~60 | embeddings |
| `KernelLanguageEntropy` | — | ~80 | embeddings (Gram matrix, related to EigenScore) |
| `DegMat` / `Eccentricity` / `EigValLaplacian` / `NumSemSets` | Lin et al. 2023 (same paper as EigenScore) | ~30 each | embeddings |
| `RAUQ` | Vazhentsev et al. 2025 | ~60 | whitebox |
| `CSL` | Lin et al. 2024 | ~50 | whitebox |
| `Focus` | Zhang et al. 2023 | ~40 | attention weights (HF only) |
| `EPTtu`/`EPTdu`/`EPTmi`/`EPTrmi`/`EPTepkl` | Malinin & Gales 2020 (ensemble predictive entropy variants) | ~200 total | ensemble of models |
| Claim-level variants (`*Claim` classes) | Fadeeva et al. 2023 TACL | ~30 each (wrappers) | varies |

### Metrics LUB lacks

| Metric | What it measures |
|--------|------------------|
| `ReversedPairsProportion` (RPP) | Fraction of (correct, incorrect) pairs where the model is *more* confident on the wrong answer. Lower is better. Rank correlation complement. |
| `SpearmanRankCorrelation` | Spearman ρ between confidence and correctness. |
| `KendallTauCorrelation` | Kendall τ between confidence and correctness. |
| `PRAUC` | Precision-recall AUC (correctness as positive class, confidence as score). Better than AUROC when classes are imbalanced. |
| `IsotonicPCC` | Pearson correlation *after* isotonic recalibration — measures residual signal. |

### Patterns to copy

1. **Claim-level decomposition**: every sequence-level estimator has a
   `*Claim` wrapper that splits the answer into atomic claims (via an
   NLI/entailment step) and scores each claim independently. LUB could
   add a `claim_decompose(result) -> list[UncertaintyResult]` utility
   at L2, ~100 lines plus a lazy NLI dependency.
2. **`stat_calculator` caching**: Polygraph pre-computes logprobs,
   embeddings, and attention in a shared `stat_calculator` per batch,
   so estimators don't redundantly call the model. LUB's
   `Estimator.score()` calls the backend directly per-prompt; adding a
   `BatchContext` cache object passed through the call would eliminate
   N×M redundant forward passes when running N estimators on M prompts.

### Top 3 to port

1. **`MahalanobisDistanceSeq`** — density-based OOD estimator. ~80 lines at L2
   (`src/lub/uncertainty/mahalanobis.py`). Needs a calibration embedding set
   (like `ConformalEstimator.fit()`). Cite Lee et al. 2018. High banking value:
   OOD detection is literally what SR 11-7 calls "model boundary monitoring."
2. **`TokenSAR`** — semantic-aware ranking of token contributions. ~60 lines at
   L2 (`src/lub/uncertainty/sar.py`). Needs logprobs. Cite Duan et al. 2023.
   Cheaper than semantic entropy, better than raw token logprob.
3. **RPP + Spearman + Kendall as L3 meta-metrics** — ~40 lines total in
   `src/lub/calibration/correlation.py`. Pure numpy. These are what reviewers
   look at when comparing estimators side-by-side. Add to `compute_all()`.

### Do not port

- **EPT/PET/EPS ensemble variants** — need multiple independently trained
  models. No DummyBackend hermetic test possible. Massive scope.
- **Claim-level decomposition** — adds NLI dependency to L2. Defer to
  post-v0.2.0 and ship as an optional extra (`pip install lub[claims]`).
- **Focus (attention-weight estimator)** — couples to HF internals
  (`model.attentions`). Fragile across model families. Low generality.

---

## Repo 2: Uncertainty Toolbox

### License: MIT — Compatible with Apache-2.0? Yes

### Methods LUB lacks

None — Uncertainty Toolbox is metrics-only (no uncertainty estimators).

### Metrics LUB lacks

| Metric | Formula sketch | Paper |
|--------|---------------|-------|
| **RMSCE** (Root Mean Squared Calibration Error) | `sqrt(mean((bin_acc - bin_conf)²))` | Naeini et al. 2015 |
| **Adversarial Group Calibration** | Worst-case miscalibration over all subgroups of size ≥ k. `max_S⊂D (cal_error(S))` | Zhao et al. 2021 "Individual Calibration with Randomized Forecasting" |
| **CRPS** (Continuous Ranked Probability Score) | `CRPS = σ[-1/√π + 2φ(z) + z(2Φ(z)-1)]` for Gaussian | Gneiting & Raftery 2007 |
| **NLL** (Gaussian Negative Log-Likelihood) | `-Σ log N(y; μ, σ²)` | Standard |
| **Check Score** (Pinball Loss) | `Σ_q (q - 𝟙(y < q̂)) × (y - q̂)` | Koenker & Bassett 1978 |
| **Interval Score** (Winkler Score) | `(u-l) + 2/α × [max(l-y,0) + max(y-u,0)]` | Winkler 1972 |

### Patterns to copy

1. **Callable-factory recalibration** — `get_std_recalibrator(cal_data)`
   returns a `Callable[[ndarray], ndarray]` closure instead of a
   stateful object. LUB's `normalizers.py` uses fit/transform (sklearn
   convention); offering **both** patterns is useful because the
   closure form is easier to serialize (just save the ratio or the
   isotonic breakpoints).
2. **`get_all_metrics()` single-call aggregator** — returns a nested
   dict of *every* metric in one pass. LUB has `compute_all()` but
   it doesn't include the scoring rules or rank correlations. Extend
   `compute_all()` to accept an `include_scoring_rules=True` flag.

### Top 3 to port

1. **CRPS** — the gold-standard proper scoring rule for probabilistic
   forecasts. ~30 lines at L3 (`src/lub/calibration/scoring_rules.py`).
   Pure numpy (Gaussian closed form). Cite Gneiting & Raftery 2007.
   Banking value: CRPS is the metric model validators ask for when they
   hear "calibration" — it's what they learned in stats grad school.
2. **RMSCE** — complements ECE by penalizing large bin errors more. ~15
   lines, add to `metrics.py`. Cite Naeini et al. 2015.
3. **Adversarial Group Calibration** — worst-case subgroup
   miscalibration. ~60 lines. Directly maps to NIST AI RMF MEASURE 2.11
   (fairness). Cite Zhao et al. 2021.

### Do not port

- **Interval score / check score** — LUB outputs scalar confidence, not
  prediction intervals. These metrics require `(lower, upper)` bounds,
  which no current LUB estimator produces. Defer until/unless a
  quantile-regression estimator is added.
- **NLL** — needs a Gaussian assumption on the predictive distribution.
  LUB's estimators output a scalar confidence in [0,1], not a mean+std
  pair. Would require rethinking the `UncertaintyResult` contract.

---

## Repo 3: ConformalLLM

### License: Not specified (check repo) — Compatible? Unknown, likely research-only

### Methods LUB lacks

Minimal. The repo implements conformal prediction for MCQ tasks using
LLaMA softmax scores — essentially the same split-conformal procedure
LUB already has in `conformal.py` but specialized to multiple-choice
answer sets.

### Metrics LUB lacks

None beyond what LUB has. Standard accuracy + coverage.

### Patterns to copy

1. **MCQ-specific nonconformity score** — instead of using mean token
   logprob (LUB's default), ConformalLLM uses `1 - softmax(correct_option)`
   as the nonconformity score. LUB's `ConformalEstimator` could accept a
   pluggable `nonconformity_fn` parameter (~10 lines) to support this.

### Top 3 to port

1. **Pluggable nonconformity function on ConformalEstimator** — ~10 lines,
   L2. Low effort, high flexibility. No paper needed (engineering refinement).

### Do not port

- Everything else. The repo is thin research code tied to LLaMA + MCQ.
  LUB's conformal is already more general.

---

## Combined Priority List

Ranked by **(value to banking compliance) / (effort)**:

| Rank | Idea | ~Lines | Target file |
|------|------|--------|-------------|
| 1 | **CRPS** proper scoring rule (Gaussian closed form) | ~30 | `src/lub/calibration/scoring_rules.py` |
| 2 | **RMSCE** + extend `compute_all()` | ~20 | `src/lub/calibration/metrics.py` |
| 3 | **RPP + Spearman ρ + Kendall τ** rank correlations | ~40 | `src/lub/calibration/correlation.py` |
| 4 | **MahalanobisDistanceSeq** OOD estimator | ~80 | `src/lub/uncertainty/mahalanobis.py` |
| 5 | **Adversarial Group Calibration** worst-case subgroup | ~60 | `src/lub/calibration/metrics.py` |

Items 1-3 are pure-numpy L3 modules, testable against DummyBackend,
shippable in a single PR each. Item 4 needs a calibration set (same
pattern as `ConformalEstimator.fit()`). Item 5 maps directly to NIST
AI RMF MEASURE 2.11 (fairness) — strong governance evidence.
