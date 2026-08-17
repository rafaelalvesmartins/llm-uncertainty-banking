# arXiv Submission Info

**Paper:** "Calibrated LLMs for Regulated Banking: A Benchmark and NIST AI RMF Reporting Pipeline for Uncertainty Quantification in Financial LLM Deployments"

**Authors:** Rafael Martins Alves (Banco de Brasília, UNICAMP)

**arXiv ID:** [Pending — will be assigned upon submission]

**Categories:** cs.CL (primary), cs.LG (secondary)

**Submission status:** Ready for arXiv (see `docs/arxiv_submission_template.txt`)

## Files in this submission:

- `src/lub/` — Main library code (86 modules, 732 tests, 93% coverage)
- `docs/tech-report/draft.md` — Full manuscript (653 lines, 9 sections)
- `benchmarks/` — Reproducibility artifacts, dataset hashes, seeded runs
- `CITATION.cff` — Citation metadata
- `scripts/arxiv_benchmark_suite.py` — Reproducible benchmark runner
- `scripts/generate_arxiv_email.py` — Email template generator

## To reproduce:

```bash
# Run full benchmark suite (requires GPU or Colab)
python scripts/arxiv_benchmark_suite.py \
    --models qwen2.5-0.5b mistral-0.5b \
    --estimators token_logprob self_consistency semantic_entropy \
    --datasets br_regulatory finqa --seed 0

# This generates figures (Figure 1, 2) and populates Section 5 of the paper
```

## Regulatory compliance:

6 canonical regimes (verified against `src/lub/reports/crosswalk_data.toml`):

- NIST AI 600-1 (GenAI Profile of AI RMF 1.0) ✓
- EU AI Act (Regulation 2024/1689) ✓
- BCBS 239 ✓ (renamed 2026-04-26 from BCBS d475)
- BCB Res. 4.893/2021 ✓
- ISO/IEC 23894:2023 ✓
- ISO/IEC 42001:2023 ✓

SR 11-7 / OCC 2011-12 three-pillar mapping cross-referenced via library README (not a separate `Regime` enum).

---

**Submission date:** April 17, 2026
**Manuscript version:** v0.1
