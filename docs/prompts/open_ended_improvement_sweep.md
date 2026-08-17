# Open-ended improvement sweep — find ideas LUB hasn't considered

**Use:** paste the block below the `---` line into a fresh LLM chat with
web browsing enabled (Claude, GPT-4, Gemini, Perplexity). Save the
output as `13c_Sweep_OpenEnded_[DATE].md` in this folder.

**Goal:** surface companies, open-source projects, papers, and design
patterns that are adjacent to LUB but were not covered by Prompts 1–5.
Prompts 1–5 already covered LM-Polygraph, Uncertainty Toolbox,
ConformalLLM, Guardrails AI, NeMo Guardrails, Giskard, PIXIU/FinBen,
lm-evaluation-harness, Inspect AI, TruLens, Ragas, aibom-scanner,
promptfoo, semantic_uncertainty, PolicyBind. Do not re-cover those.

---

# Competitor + idea sweep for `llm-uncertainty-banking`

## The project in one paragraph

`llm-uncertainty-banking` (LUB) is a Python library, Apache 2.0,
`pip install lub`, that quantifies LLM output uncertainty and maps it
to regulatory compliance artifacts for the US banking sector. It
targets Federal Reserve SR 11-7 (model risk management), Executive
Order 14110 / America's AI Action Plan (trustworthy AI), and the NIST
AI Risk Management Framework 1.0. The library is the substantive
technical work behind an EB-2 NIW petition, so it is both a real
research project and a petition exhibit.

## What LUB currently ships (do not suggest duplicates of these)

- **L1 backends (5):** HuggingFace, OpenAI, Anthropic, vLLM, a
  deterministic Dummy. Whitebox vs blackbox split documented; every
  backend has a stable `REGISTRY_KEY`.
- **L2 uncertainty estimators (18):**
  token_logprob, perplexity, token_sar (Duan 2023),
  self_consistency, semantic_entropy (Kuhn 2023), eigenscore
  (Lin 2023), mahalanobis (Ren 2023), p_true (Kadavath 2022),
  verbalized_1s, verbalized_2s (Tian 2023), conformal (Vovk 2005),
  conformal_sampling (Quach 2024 ICLR), mc_dropout (Gal 2016),
  ccp (Fadeeva 2024 ACL), claim_level, ensemble, self_certainty,
  lmpolygraph (bridge to Fadeeva 2023).
- **L3 calibration metrics (~15):** ECE, RMSCE, ENCE,
  miscalibration_area, sharpness, missing_ratio, PRR,
  refusal_auroc, MCC, Kendall tau, Spearman rank, reversed_pairs,
  adversarial_group_calibration, pinball_loss, NLL, CRPS (Gaussian),
  interval_score.
- **L3 normalizers (5):** identity, minmax, binned PCC, isotonic PAV,
  quantile. All JSON-serializable, no sklearn dependency.
- **L4 datasets (8):** FinQA, ConvFinQA, TAT-QA, BR-Regulatory,
  german_credit, australian_credit, fpb, fiqa_sa. Typer CLI via
  `lub benchmark --config configs/eval/*.toml`.
- **L5 AI RMF reporter:** Jinja HTML/MD templates, metric →
  (subcategory, trust_dimension) mapping, governance integration.
- **Governance layer:** `rails.py` (input/output validator chains,
  NeMo-inspired), `policies.py` (ABSTAIN, FLAG, PASSTHROUGH, RAISE,
  REASK — Guardrails-inspired), `guard.py` (UncertaintyGuard wrapping
  pipelines), all mapped to AI RMF MANAGE sub-categories.
- **Infrastructure:** 309 tests, ruff clean, import-linter
  layered-architecture contract, CI/CD on GitHub Actions, MkDocs
  site, `scripts/capture_evidence.py` for monthly metric snapshots.

## What I want from you

Go beyond the 15 already-scanned projects and return a structured
report with these sections.

### Section A — Adjacent open-source projects (≥ 8, novel)

For each: GitHub URL, stars, license, last commit date, one-line
pitch, one paragraph on the specific pattern / algorithm / API that
LUB should study, and a one-line verdict on whether the pattern
belongs in LUB's architecture.

Focus areas:
1. **LLM observability / tracing** — OpenTelemetry for LLMs, trace
   schema standards, eval replay tooling
2. **Financial-domain ML beyond PIXIU** — fraud-detection benchmarks,
   AML/KYC public datasets, credit-risk research codebases
3. **Formal verification for ML** — projects that check model
   outputs against specifications (Polaris, IBM LMDiagnosis,
   Microsoft Counterfit, anything from the AI red-teaming world)
4. **Compliance-as-code** — projects that express regulatory
   requirements as testable artifacts (OSCAL, Regolith, GDPR-bench,
   anything from the GRC tooling world)
5. **Uncertainty in scientific ML** — Bayesian deep learning libs,
   Gaussian process libs, anything from the physical-sciences ML
   world that might port to LLMs

### Section B — Company patterns (≥ 5 companies)

For each: company name, product name, one paragraph on the specific
reporting artifact / governance pattern / UX pattern LUB should
mimic, whether they publish enough detail to copy, and what the
portability cost would be.

Focus areas:
1. **Model monitoring products** — Arize, WhyLabs, Fiddler, Aporia,
   Mona, Giskard, Arthur, Superwise — ignore the 2 already covered,
   pick 4+ new
2. **Banking model-risk platforms** — Moody's Analytics Enterprise
   Risk Solutions, SAS Model Implementation Platform, IBM Watson
   AIOps, Zest AI, Upstart model monitoring
3. **Regulatory reporting SaaS** — how do Workiva / Ceros / OneStream
   structure audit-ready reports? Which of their output schemas
   could be emulated by LUB's L5?
4. **Academic / government tooling** — US Census AI toolbox, OMB
   M-24-10, Treasury OCC's own AI guidance tooling (if any), ECB's
   supervisory AI tooling

### Section C — Research directions (≥ 5 papers from 2024–2026)

Papers published after the LM-Polygraph and semantic-entropy work
that would extend LUB's estimator set or evaluation protocol. For
each: full citation, arXiv ID, one-paragraph summary of the novel
contribution, and a one-line note on implementation cost in LUB.

Focus on:
- Hallucination detection for long-form generation
- Uncertainty under retrieval-augmented generation (RAG)
- Uncertainty for tool-using agents / function calls
- Distribution-free calibration guarantees beyond Quach 2024
- Fact-level uncertainty methods beyond CCP

### Section D — Anti-patterns to flag

What are 3–5 fashionable ideas that LUB should explicitly **not**
adopt? Examples of what I mean:
- LangChain-style heavy abstraction (LUB stays small)
- Proprietary DSLs (LUB stays pydantic + TOML)
- Vendor-locked observability (LUB stays JSON-schema portable)

Each anti-pattern should be one paragraph with: what it looks like,
why it's tempting, why it would hurt LUB specifically.

### Section E — The single most leveraged addition

Of everything you found, pick ONE addition. Say what it is, why it
beats everything else on the list, estimate the implementation cost
in LOC, and sketch the interface it would take in LUB (which layer,
which file, which existing abstractions it composes with).

## Rules

- Fetch primary sources. Do not invent GitHub stars or paper
  citations. Say "unknown" if you cannot verify.
- No marketing language. Engineer-to-engineer tone.
- If you find something that duplicates what LUB already has, skip
  it silently — I don't need confirmation of existing coverage.
- Flag anything published after 2026-01-01 as NEW.
- Hard length cap: 1500 words across all sections.
- End with a one-line "date of scan" line so the artifact is
  auditable.
