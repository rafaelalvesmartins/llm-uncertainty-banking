# Stage G — Qwen benchmark re-run plan

**Critical-path item G** (per daily-digest 2026-05-18). Current state of
the headline Qwen results: **Acc 0.000 / AUROC 0.500** across 4 of 22
estimators. The artifact at `docs/tech-report/artifacts/results_table_qwen.md`
correctly warns "DO NOT submit to arXiv, USCIS, or recommenders until
this file is fixed". This document picks the resolution path and
captures the exact command(s) to execute when GPU time is available.

The point of this doc is to **eliminate the decision overhead at GPU
time**. When you sit down with the GPU, you copy a command, you don't
re-design the experiment.

## Decision — recommended path: (a) full sweep on Llama-3-8B via Ollama

The 3 resolution paths from `results_table_qwen.md`:

| Path | Cost | Defensibility | When to choose |
|---|---|---|---|
| **(a) Full 22-estimator sweep on Qwen2.5-7B or Llama-3-8B** | ~1 GPU-day or 2-4 CPU-hours via Ollama on the host you already have | **High** — replaces the broken table entirely with a credible one | If you have ANY GPU/CPU compute available before filing |
| (b) Pivot headline to BR-Regulatory binary yes/no on the small model | ~1 hour | Medium — works around the model size limit but the small-model framing is itself worth scrutinizing | If (a) is not feasible at all and you must ship something |
| (c) Freeze current as "calibration-metrics demonstration" + 1 row on Anthropic API | ~30 min + tokens | Medium — honest, but loses the "22-estimator sweep" narrative | If (a) and (b) are both blocked and you have Anthropic API credit |

**Recommendation: (a).** Ollama is already installed and running on the
host (verified via the bridge-ui LIVE LLM mode in round 10). Llama-3-8B
is a strong open-weight banking-capable model. The full sweep replaces
the broken table with a credible one and preserves the "22-estimator
crosswalk" claim that is the petition's strongest novelty contribution.

## The command — copy and run when GPU/CPU time is available

Pre-flight: confirm Ollama is up and the model is pulled.

```bash
# 1. Verify Ollama is running
curl -s http://localhost:11434/api/tags | python -c "import sys,json; print(json.load(sys.stdin))"

# 2. Pull Llama-3-8B if not already
ollama pull llama3.1:8b
```

The sweep itself. Run from the project root.

```bash
cd 06_Projeto_GitHub/llm-uncertainty-banking

# Output directory
mkdir -p docs/tech-report/artifacts/llama3_sweep

# 22-estimator sweep on br_regulatory (the canonical headline dataset)
ESTIMATORS=(
    adaptive_conformal ccp claim_level conformal conformal_sampling
    eigenscore ensemble epistemic_aleatoric graph_laplacian lmpolygraph
    mahalanobis mondrian_conformal monte_carlo_dropout p_true perplexity
    sar self_certainty self_consistency semantic_entropy sentence_sar
    token_logprob verbalized
)

for est in "${ESTIMATORS[@]}"; do
    echo "=== $est at $(date -u +%H:%M:%S) ==="
    python -c "from lub.cli import app; app([
        'benchmark',
        '--backend', 'ollama',
        '--model', 'llama3.1:8b',
        '--estimator', '$est',
        '--dataset', 'br_regulatory',
        '--limit', '50',
        '--seed', '42',
        '--out', 'docs/tech-report/artifacts/llama3_sweep/'
    ])" 2>&1 | tee "docs/tech-report/artifacts/llama3_sweep/log_${est}.txt"
done
```

Time estimate (CPU, Ollama llama3.1:8b at ~20s/inference, 50 examples ×
22 estimators ≈ 1100 inferences): **~6 hours wall time** if estimators
share inferences efficiently, **~12 hours** if each estimator does
its own pass. GPU brings this to 30-60 min.

## After the sweep — assembling the new results table

The current canonical table is at
`docs/tech-report/artifacts/results_table_qwen.md`. The sweep writes
22 JSON files to `docs/tech-report/artifacts/llama3_sweep/`. To
regenerate the table:

```bash
python -c "from lub.cli import app; app([
    'report',
    '--input-dir', 'docs/tech-report/artifacts/llama3_sweep/',
    '--format', 'markdown',
    '--out', 'docs/tech-report/artifacts/results_table_llama3.md'
])"
```

Then **manually compare** the two tables side-by-side. The acceptance
criterion for replacing the canonical artifact:

- At least one estimator achieves **accuracy >= 0.40** on br_regulatory
  (i.e. better than random for a 5-option question; ideally >= 0.60).
- At least one estimator achieves **refusal_auroc >= 0.65** (the
  calibration metric — if confidence ranks correct vs incorrect
  meaningfully).
- ECE for the best estimator is **< 0.30** (lower than the current
  Qwen 0.67).

If those bars are met: replace `results_table_qwen.md` with
`results_table_llama3.md`, update the warning header to a "validated
2026-05-XX" footer, regenerate the dependent paper sections.

If those bars are NOT met: do not ship. Fall back to path (b) or (c).

## Pre-flight sanity checks (cheap, do these first)

Before burning the GPU-day, verify the eval harness produces non-trivial
results on a known-good baseline. Run a SINGLE estimator on a SMALL
limit against a backend you trust:

```bash
# Sanity: dummy backend should be ~50% accuracy by construction
python -c "from lub.cli import app; app([
    'benchmark',
    '--backend', 'dummy',
    '--model', 'random',
    '--estimator', 'token_logprob',
    '--dataset', 'br_regulatory',
    '--limit', '20',
    '--out', '/tmp/sanity_dummy/'
])"
# Expected: accuracy roughly 0.20-0.30 (random over 5 options).
# If you see exactly 0.0 with non-zero confidence, the answer extractor
# is broken — fix that BEFORE running on Llama.
```

If dummy passes but the previous Qwen run was 0.0, the issue was
model-size, not harness. Proceed with confidence to the Llama sweep.

If dummy ALSO returns 0.0, the answer-extraction template is broken.
Fix `src/lub/benchmarks/br_regulatory.py` (the answer parser) before
running anything else.

## Petition narrative impact

This stage clears the single biggest external-credibility risk in the
petition. The current Qwen table is the first thing a USCIS adjudicator
or peer reviewer would Google after reading the technical report.
Replacing 0.000 / 0.500 with credible numbers is the highest-leverage
single technical action remaining before filing 2026-07-01.

T-43 days at the time of writing.
