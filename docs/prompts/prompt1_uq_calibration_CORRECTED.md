# Prompt 1 of 5 — Uncertainty Estimation & Calibration Metrics
# Theme: Core UQ methods and calibration metrics LUB should match or exceed
# Targets: LM-Polygraph, Uncertainty Toolbox, ConformalLLM
# Last verified against codebase: 2026-04-16 (206 tests passing)

---

## How to use

1. Open a fresh LLM chat (Claude, GPT, Gemini) with web browsing enabled.
2. Paste everything below the --- line.
3. The LLM will fetch each repo and produce a structured report.
4. Save output as `13b_Sweep_UQ_Calibration.md`

---

## Prompt — start here

You are a senior Python engineer doing a competitive feature-gap analysis
for **llm-uncertainty-banking** (LUB), an Apache-2.0 library for uncertainty
quantification of LLM outputs in regulated banking, with NIST AI RMF reporting.

### LUB's current inventory (do NOT re-suggest these):

**L1 backends (5):** Dummy, HuggingFace, OpenAI, Anthropic, vLLM

**L2 estimators (18):**
- token_logprob — mean token logprob → exp confidence
- perplexity — perplexity-based confidence
- self_consistency — Wang et al. 2022 majority vote
- semantic_entropy — Kuhn et al. 2023 NLI clustering
- conformal — split conformal with coverage guarantee, JSON-serializable
- conformal_sampling — sampling-based conformal variant
- monte_carlo_dropout — Gal & Ghahramani 2016 (HF only)
- p_true — reflexive "is this answer True?" probing
- eigenscore — diversity score without NLI model
- verbalized_1s / verbalized_2s — ask model to self-rate 0-100
- lmpolygraph — bridge to LM-Polygraph estimators
- ensemble — ensemble-based uncertainty
- mahalanobis — Mahalanobis distance in hidden-state space
- sar — Token Sequence-level Attention Ratio
- self_certainty — model self-certainty probing
- ccp — Conformal Calibration via Prediction sets
- claim_level — claim-level decomposition estimator

**L3 calibration metrics (in `calibration/metrics.py`):**
- ECE (expected calibration error, equal-width bins)
- Brier score
- refusal AUROC (rank-sum with tie handling)
- miscalibration_area (bin-free, trapezoidal)
- sharpness
- missing_ratio
- reliability_curve
- spearman_rank_correlation
- kendall_tau
- adversarial_group_calibration

**L3 scoring rules (in `calibration/scoring_rules.py`):**
- interval_score
- crps_gaussian (closed-form Gaussian CRPS)
- crps_from_confidence (empirical CRPS from confidence + correctness)

**L3 selective prediction (in `calibration/selective.py`):**
- PRR (Prediction-Rejection Ratio)
- risk-coverage curve
- AURC (area under risk-coverage curve)

**L3 normalizers (in `calibration/normalizers.py`):**
- IdentityNormalizer
- MinMaxNormalizer
- BinnedPCCNormalizer (binned probability-calibrated confidence)
- IsotonicNormalizer (isotonic regression recalibration)
- QuantileNormalizer

**L3 plots (in `calibration/plots.py`):**
- reliability diagram (matplotlib)
- confidence histogram

**L4 benchmarks:** FinQA, ConvFinQA, TAT-QA, Brazilian regulatory QA (20 hand-crafted)

**L5 reports:** NIST AI RMF Jinja2 template (Govern/Map/Measure/Manage),
metric → sub-category mapping, markdown + HTML renderer

**Governance:** rails.py (NeMo-inspired I/O hooks), policies.py
(ABSTAIN/FLAG/PASSTHROUGH/RAISE → NIST AI RMF MANAGE mapping), guard.py

**Infra:** 206 tests, DummyBackend, ruff+mypy+import-linter, 5-layer architecture

---

### Review these 3 repos. For EACH repo, answer ALL sections below.

#### Repo 1: LM-Polygraph
- **URL:** https://github.com/IINemo/lm-polygraph
- **Focus on:** `src/lm_polygraph/estimators/` directory (48 files),
  `src/lm_polygraph/ue_metrics/`, `src/lm_polygraph/normalizers/`
- **License:** MIT
- **Stars:** 465 | **Status:** Very active (v0.6.0, Apr 2026, TACL-2025 paper)

#### Repo 2: Uncertainty Toolbox
- **URL:** https://github.com/uncertainty-toolbox/uncertainty-toolbox
- **Focus on:** `uncertainty_toolbox/metrics_calibration.py`,
  `uncertainty_toolbox/metrics_scoring_rule.py`, `uncertainty_toolbox/recalibration.py`
- **License:** MIT
- **Stars:** ~1.9k | **Status:** Mature but dormant (last commit Jan 2023)

#### Repo 3: ConformalLLM
- **URL:** https://github.com/bhaweshiitk/ConformalLLM
- **Focus on:** Conformal prediction extensions for LLMs
- **License:** Check LICENSE file
- **Stars:** 70 | **Status:** Research code

---

### For EACH of the 3 repos, answer:

**1. Estimators/methods LUB doesn't have.**
List every uncertainty, confidence, or calibration method NOT in LUB's list above.
For each: name, paper (author+year), ~lines of code, needs logprobs/embeddings/blackbox?

**2. Metrics LUB doesn't have.**
List every evaluation metric beyond LUB's list above.
For each: name, formula sketch, paper reference.

Key metrics to check whether LUB has them (answer YES or NO for each):
- CRPS (Continuous Ranked Probability Score) — YES, LUB has crps_gaussian + crps_from_confidence
- NLL (Negative Log-Likelihood) — check if LUB has a standalone NLL metric
- Check Score / Pinball Loss — check if distinct from interval_score
- Interval Score (Winkler) — YES, LUB has interval_score
- RMSCE (Root Mean Squared Calibration Error) — check
- Adversarial Group Calibration — YES, LUB has it
- ENCE (Expected Normalized Calibration Error) — check
- Spearman / Kendall rank correlation — YES, LUB has both

**3. Architecture patterns worth copying.**
Describe 1-3 design patterns (NOT features) that LUB could adapt as a
small module (<200 lines). Examples: estimator registry, stat_calculator
caching, config system, result serialization.

**4. Top 3 things to copy, ranked by (banking value)/(effort).**
For each: what to build, estimated lines, which LUB layer (L1-L5),
file path to create, and paper to cite.

**5. What NOT to copy.**
Scope-creep traps, heavy dependencies, things needing training data
(breaks DummyBackend hermeticity), server components.

### Output format
Under 1000 words total. Use this structure:

## Repo Name
### License: [license] — Compatible with Apache-2.0? [yes/no]
### Methods LUB lacks
### Metrics LUB lacks
### Patterns to copy
### Top 3 to port
### Do not port

## Combined Priority List
Rank the top 5 ideas across ALL 3 repos by (value to banking compliance)/(effort).
For each: one-liner description, ~lines of code, target file path in LUB.
