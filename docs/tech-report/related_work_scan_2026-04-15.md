# Related Work Competitive Scan — 2026-04-15

Implementation-focused review of open-source LLM uncertainty quantification and
AI governance projects. Goal: extract concrete, portable ideas for LUB and feed
Section 2 (Related Work) of the tech report draft.

## A. "Steal immediately" list (ranked impact × effort)

| # | Source | Feature | Maps to LUB | Effort |
|---|---|---|---|---|
| 1 | lm-polygraph | Estimator base class + registry (category-tagged: info / diversity / density / reflexive), CLI instantiates by name | L2: add `Estimator` ABC with `.category`, `@register_estimator("name")` decorator, global `ESTIMATORS` dict wired into `cli.py` | M |
| 2 | lm-eval-harness | YAML task configs + `--use_cache <dir>` + `--cache_requests` skipping already-evaluated samples | L4: `src/lub/benchmarks/configs/*.yaml` + `SampleCache` keyed on `sha1(model_id + prompt + params)` in `benchmarks/base.py` | M |
| 3 | jlko/semantic_uncertainty | `get_semantic_ids()`, `logsumexp_by_id()`, `predictive_entropy_rao()`, DeBERTa MNLI entailment default, cluster-assignment entropy as separate metric | L2: rewrite `semantic_entropy.py` to expose rao / regular / cluster-assignment variants, pluggable entailment backend | S-M |
| 4 | uncertainty-toolbox | `get_all_metrics()` one-shot dump + isotonic recalibration + sharpness + miscalibration area | L3: add `calibration/recalibration.py` (isotonic + Platt), add `miscalibration_area`, `sharpness`, `get_all_metrics()` facade | S |
| 5 | lm-polygraph | `BlackboxModel` vs `WhiteboxModel` split; auto-downgrade estimator set for blackbox backends | L1: `WhiteboxModel`/`BlackboxModel` mixins in `wrappers/base.py`; estimators declare `requires_logprobs = True` | M |
| 6 | lm-polygraph | Hydra/OmegaConf config for runs — every run is a committed YAML | L4/CLI: `lub eval --config-name=finqa_vllm.yaml`, configs under `configs/eval/` | M |
| 7 | Varal7/conformal-language-modeling | Dual stopping + rejection rules for sampling-based conformal sets (Quach et al. 2024) | L2: `uncertainty/conformal_sampling.py` alongside existing split-conformal | M-L |
| 8 | PIXIU / FLARE | Task base classes (`Classification`, `QA`, `SequentialLabeling`, `NumberUnderstanding`) + **Missing Ratio** metric (proxy for abstention / refusal — directly relevant for banking) | L4: `benchmarks/base.py::Task` subclasses; `missing_ratio` in `calibration/metrics.py` | S |
| 9 | Guardrails-AI | Input/Output Guard pattern wrapping LLM calls with validator chains, pydantic-typed outputs | L1/L5: `src/lub/guards/` with pre/post validators; guard firings emitted into RMF report | S |
| 10 | UQLM (cvs-health) | Tunable ensemble of scorers (token-prob + consistency + LLM-judge) returning single [0,1] confidence, black-box/white-box split | L2: `uncertainty/ensemble.py` with weighted blend calibrated on dev split | S |

## B. Estimators LUB is missing

Ranked by implementation cost × banking relevance:

1. **Perplexity / MeanTokenEntropy** — trivial extension of token-logprob (Fadeeva et al. 2023)
2. **Semantic Entropy Rao variant + cluster-assignment entropy** — Farquhar et al., Nature 2024
3. **SAR / TokenSAR / SentenceSAR** — Duan et al. 2023, "Shifting Attention to Relevance"
4. **p(True) self-evaluation** — Kadavath et al. 2022
5. **Verbalized uncertainty 1S/2S** — Tian et al. 2023 (critical for blackbox Anthropic/OpenAI path)
6. **EigenScore / Kernel Language Entropy / NumSets / Eccentricity** — Lin et al. 2023 / Nikitin et al. 2024 (graph-spectral diversity)
7. **Mahalanobis / Relative Mahalanobis on hidden states** — Ren et al. 2023 (density-based, whitebox only)
8. **Claim-Conditioned Probability (CCP)** — Fadeeva et al. 2024 (fact-level UQ, excellent fit for banking claims)
9. **Conformal sampling with dual stopping/rejection rules** — Quach et al. 2024
10. **p_ik embedding classifier** — Farquhar et al. baseline (logistic on last-layer embeddings)

## C. Governance patterns worth copying

- **Responsible AI Dashboard sections** → mirror as fixed sections in LUB's RMF Jinja report: `ModelOverview`, `ErrorAnalysis`, `Fairness`, `Interpretability`, `Counterfactual`, `DataBalance`. Empty sections still signal RMF coverage to auditors.
- **NeMo Guardrails five rail types** (Input / Dialog / Retrieval / Execution / Output) → directly map to NIST AI RMF "Manage" function subcategories. Add a rail-coverage matrix to the report.
- **Guardrails Index risk categories** (6 categories × 24 guards) → adopt as a "Risk Coverage" table in L5 report, one row per category with which LUB estimator/guard addresses it.
- **Credo AI Lens `Assessment` abstraction** → wrap each estimator+threshold pair as an `Assessment` with pass/fail/warn, aggregated into a single governance verdict per run.
- **Guardrails pydantic-typed outputs** → enforce a `LubReport` pydantic schema as the single source of truth for HTML and MD reports.

## D. Benchmark runner lessons

- **lm-eval-harness**: (a) `--use_cache <dir>` skips already-evaluated (model, task, sample) triples via SQLite or sharded JSONL on sha1; (b) `--log_samples` writes `<task>_eval_samples.json` alongside `results.json` — adopt exact filenames; (c) `--num_fewshot` as first-class CLI flag; (d) accelerate-based data parallelism via `parallelize=True`.
- **lm-polygraph Manager + Hydra**: one `Manager` class owns (model, dataset, estimators, ue_metrics, generation_metrics) and emits a single pickle. LUB should produce one `RunArtifact` per invocation — config hash + inputs + outputs + metrics — instead of scattered files. Fingerprint = `sha1(config_yaml + dataset_version + model_id + lub_version)`.
- **PIXIU**: task registration via plain `"task_name": module.ClassName` dict in `tasks/__init__.py` — no entry points needed.
- **FinanceBench**: ship dataset as JSONL with `evidence_text`, `evidence_doc_name`, `evidence_page_num` fields. LUB's `BR-Regulatory` should adopt this schema for future page-level grounding evaluations.
- **Result schema**: adopt lm-eval's `results.json` + `samples.jsonl` convention and publish a JSON Schema under `docs/schemas/`.

## E. "Don't do this" warnings

- **TorchUQ**: 97.7% Jupyter notebooks — hard to test and package. Keep LUB notebook-free in `src/`; notebooks only under `examples/`.
- **semantic_uncertainty (jlko)**: three disconnected scripts with state passed via pickles — easy to go stale. LUB's single `Pipeline` is already better; don't regress.
- **Credo AI Lens**: **archived July 2024**. Do not take runtime dependency; pull ideas only. Signals governance-tool risk — LUB should avoid deep third-party governance SDK coupling.
- **lm-polygraph Hydra**: Hydra multi-run / override syntax creates config sprawl; cap LUB at single-file YAML + CLI overrides, no Hydra groups.
- **Guardrails RAIL spec**: XML-ish DSL on top of pydantic — redundant. Use pydantic directly; do not invent a DSL.
- **Responsible AI Toolbox dashboards**: heavy npm `@responsible-ai/model-assessment` React widgets. LUB should stay static HTML/MD from Jinja; no JS build step.
- **FinanceBench evaluation**: scoring is manual human review of 2,400 answers — no automated grader. LUB must ship a deterministic grader (numeric tolerance + regex + optional LLM judge) or the benchmark is not reproducible.
- **PIXIU**: mixes 30+ tasks with inconsistent metric conventions — enforce a single `TaskResult` schema in LUB from day one.

## F. New / unknown projects discovered

1. **UQLM** (`cvs-health/uqlm`) — **HIGH** relevance. Python UQ-for-LLM package from CVS Health; healthcare-adjacent like banking. White-box and black-box scorers returning `[0,1]` confidence with ensemble blending. Paper: arXiv 2507.06196. Closest philosophical match to LUB — study their `Scorer` API before finalizing LUB's `Estimator` ABC.
2. **posteriors** (Normal Computing) — MEDIUM. PyTorch Bayesian/Laplace UQ on LLMs (last-layer Laplace, SWAG). Useful if LUB adds a `bayesian/` submodule.
3. **Bradley-Butcher/Conformers** — MEDIUM. Cleaner unofficial implementation of Quach et al. conformal LM; easier to port than Varal7's research code.
4. **EdinburghNLP/awesome-hallucination-detection** — LOW but useful as a literature index for L2 expansion.
5. **SeSE** (arXiv 2511.16275) — LOW/experimental. Structural-information-guided UQ; cite in related-work, do not implement yet.
6. **ACL 2025 Tutorial on UQ for LLMs** (aclanthology 2025.acl-tutorials.3) — reference to cite as state-of-the-art overview.

## Sources fetched

- https://github.com/IINemo/lm-polygraph
- https://github.com/jlko/semantic_uncertainty
- https://github.com/uncertainty-toolbox/uncertainty-toolbox
- https://github.com/torchuq/torchuq
- https://github.com/EleutherAI/lm-evaluation-harness
- https://github.com/guardrails-ai/guardrails
- https://github.com/NVIDIA/NeMo-Guardrails
- https://github.com/microsoft/responsible-ai-toolbox
- https://github.com/credo-ai/credoai_lens (archived)
- https://github.com/patronus-ai/financebench
- https://github.com/chancefocus/PIXIU
- https://github.com/Varal7/conformal-language-modeling
- https://arxiv.org/abs/2306.10193
- https://github.com/cvs-health/uqlm
- https://arxiv.org/html/2507.06196
- https://github.com/Bradley-Butcher/Conformers
- https://github.com/EdinburghNLP/awesome-hallucination-detection
- https://aclanthology.org/2025.acl-tutorials.3/

## Unreachable (declared)

- `lm-polygraph` README direct blob + readthedocs returned 403 — details above taken from the main repo landing page, which was reachable.
- `credoai-lens.readthedocs.io` did not return usable content — verify against archived repo before any implementation.
