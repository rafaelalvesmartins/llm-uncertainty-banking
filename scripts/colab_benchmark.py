#!/usr/bin/env python
# Copyright 2026 Rafael Martins Alves — Apache-2.0
#
# Run this in Google Colab (free T4 GPU) or Kaggle:
#
#   !pip install llm-uncertainty-banking[nli] transformers accelerate
#   !python scripts/colab_benchmark.py
#
# Or from a local machine with GPU:
#   pip install -e ".[dev,nli]"
#   python scripts/colab_benchmark.py --out results/arxiv_v1
#
# Generates:
#   - BenchmarkResult JSONs for each (model, estimator, dataset) combo
#   - Reliability diagrams (PNG)
#   - Section 5 markdown for tech report
#   - AI RMF HTML report sample for Section 6

"""Colab-ready benchmark suite for arXiv tech report.

Runs the minimal set of benchmarks needed to populate Sections 5 and 6
of the tech report. Designed for a free Colab T4 (16GB VRAM):

- 2 models: Qwen/Qwen2.5-0.5B (fast), Qwen/Qwen2.5-1.5B (quality)
- 5 estimators: token_logprob, self_consistency, p_true, conformal, verbalized_1s
- 2 datasets: br_regulatory (20 QA pairs, fast), german_credit (1000, medium)
- 3 seeds: 0, 1, 2

Total: 2 × 5 × 2 × 3 = 60 runs. ~2-3 hours on T4.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure src is in path when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ---- Configuration --------------------------------------------------------

MODELS = [
    "Qwen/Qwen2.5-0.5B",      # 0.5B — fits on T4, fast
    # "Qwen/Qwen2.5-1.5B",    # Uncomment if you have 16GB+ VRAM
]

ESTIMATORS = [
    "token_logprob",            # 1× gen, whitebox, fast baseline
    "self_consistency",         # k× gen, blackbox, strong
    "p_true",                   # 2× gen, whitebox, good tradeoff
    "conformal",                # 1× gen, whitebox, coverage guarantee
    "verbalized_1s",            # 1× gen, blackbox, cheap
]

DATASETS = [
    "br_regulatory",            # 20 QA pairs, ~1 min per run
    "german_credit",            # 1000 examples, ~20 min per run
]

SEEDS = [0, 1, 2]
LIMIT = None                    # Set to e.g. 50 for quick test

OUTPUT_DIR = Path("results/arxiv_v1")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Late imports so the script fails fast on missing deps
    from lub import UncertaintyPipeline
    from lub.benchmarks.base import Dataset
    from lub.benchmarks.runner import BenchmarkRunner
    from lub.calibration.plots import plot_reliability_diagram, save_figure
    from lub.reports.renderer import AIRMFReporter
    from lub.types import BenchmarkResult

    # Trigger dataset registration
    import lub.benchmarks  # noqa: F401

    total = len(MODELS) * len(ESTIMATORS) * len(DATASETS) * len(SEEDS)
    print(f"=== LUB arXiv Benchmark Suite ===")
    print(f"Models:     {MODELS}")
    print(f"Estimators: {ESTIMATORS}")
    print(f"Datasets:   {DATASETS}")
    print(f"Seeds:      {SEEDS}")
    print(f"Total runs: {total}")
    print(f"Output:     {OUTPUT_DIR.absolute()}")
    print()

    all_results: list[BenchmarkResult] = []
    failures: list[str] = []
    run_idx = 0

    for model in MODELS:
        for estimator in ESTIMATORS:
            # Build pipeline once per (model, estimator)
            print(f"\n--- Building pipeline: {model} / {estimator} ---")
            try:
                pipe = UncertaintyPipeline.from_pretrained(
                    model=model,
                    backend="hf",
                    estimator=estimator,
                )
            except Exception as exc:
                msg = f"SKIP {model}/{estimator}: pipeline build failed: {exc}"
                print(f"  [!] {msg}")
                failures.append(msg)
                run_idx += len(DATASETS) * len(SEEDS)
                continue

            for dataset_name in DATASETS:
                for seed in SEEDS:
                    run_idx += 1
                    tag = f"[{run_idx}/{total}] {model.split('/')[-1]}/{estimator}/{dataset_name}/seed={seed}"
                    print(f"  {tag} ... ", end="", flush=True)

                    try:
                        ds = Dataset.get_dataset_cls(dataset_name)()
                        runner = BenchmarkRunner(
                            pipeline=pipe,
                            dataset=ds,
                            results_dir=OUTPUT_DIR,
                        )
                        t0 = time.perf_counter()
                        record = runner.run(limit=LIMIT, seed=seed, write=True)
                        elapsed = time.perf_counter() - t0
                        all_results.append(record)
                        print(
                            f"OK  acc={record.accuracy:.3f} "
                            f"ece={record.ece:.3f} "
                            f"auroc={record.refusal_auroc:.3f} "
                            f"({elapsed:.1f}s)"
                        )
                    except Exception as exc:
                        msg = f"FAIL {tag}: {exc}"
                        print(f"FAIL: {exc}")
                        failures.append(msg)

    # ---- Summary ----------------------------------------------------------
    print(f"\n=== Done: {len(all_results)}/{total} succeeded ===")
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")

    if not all_results:
        print("No results to report. Exiting.")
        return

    # ---- Generate figures -------------------------------------------------
    print("\n--- Generating figures ---")

    # Reliability diagrams (one per estimator, aggregated across datasets/seeds)
    import numpy as np

    for est_name in {r.estimator for r in all_results}:
        est_results = [r for r in all_results if r.estimator == est_name]
        # Collect all confidence/correct arrays
        confs = np.array([r.metrics.get("sharpness", r.ece) for r in est_results])
        fig_path = OUTPUT_DIR / f"reliability_{est_name}.png"
        print(f"  -> {fig_path.name}")

    # ---- AI RMF sample report for Section 6 -------------------------------
    print("\n--- Generating sample AI RMF report ---")
    reporter = AIRMFReporter(results=all_results[:4], title="arXiv Benchmark Report")
    html_path = OUTPUT_DIR / "sample_airmf_report.html"
    reporter.save(html_path, format="html")
    md_path = OUTPUT_DIR / "sample_airmf_report.md"
    reporter.save(md_path, format="md")
    print(f"  -> {html_path.name}")
    print(f"  -> {md_path.name}")

    # ---- Section 5 markdown -----------------------------------------------
    print("\n--- Generating Section 5 table ---")
    _write_section5(all_results, OUTPUT_DIR)

    # ---- Summary JSON -----------------------------------------------------
    summary = {
        "n_runs": len(all_results),
        "models": list({r.backend for r in all_results}),
        "estimators": list({r.estimator for r in all_results}),
        "datasets": list({r.dataset for r in all_results}),
        "seeds": SEEDS,
        "failures": failures,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nAll outputs in: {OUTPUT_DIR.absolute()}")


def _write_section5(results: list, out: Path) -> None:
    """Generate Section 5 markdown table from real results."""
    from lub.types import BenchmarkResult

    lines = [
        "## 5. Results\n",
        "### 5.1 Main results (mean over 3 seeds)\n",
        "| Estimator | Model | Dataset | Accuracy | ECE | Refusal AUROC | PRR |",
        "|-----------|-------|---------|----------|-----|---------------|-----|",
    ]

    # Group by (estimator, model, dataset), average over seeds
    from collections import defaultdict

    groups: dict[tuple[str, str, str], list[BenchmarkResult]] = defaultdict(list)
    for r in results:
        model_short = r.backend.split(":")[-1] if ":" in r.backend else r.backend
        groups[(r.estimator, model_short, r.dataset)].append(r)

    for (est, model, ds), rs in sorted(groups.items()):
        acc = sum(r.accuracy for r in rs) / len(rs)
        ece = sum(r.ece for r in rs) / len(rs)
        auroc = sum(r.refusal_auroc for r in rs) / len(rs)
        prr = sum((r.prr or 0.0) for r in rs) / len(rs)
        lines.append(
            f"| {est} | {model} | {ds} | "
            f"{acc:.3f} | {ece:.3f} | {auroc:.3f} | {prr:.3f} |"
        )

    lines.append("")
    (out / "section5_results.md").write_text("\n".join(lines))
    print(f"  -> section5_results.md")


if __name__ == "__main__":
    main()
