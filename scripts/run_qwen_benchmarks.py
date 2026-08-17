#!/usr/bin/env python
"""Run Qwen2.5-0.5B benchmarks on BR-Regulatory (CPU).

Generates real BenchmarkResult JSONs for the tech report Section 5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lub.benchmarks.br_regulatory import BrazilianRegulatoryDataset
from lub.benchmarks.runner import BenchmarkRunner
from lub.pipeline import UncertaintyPipeline
from lub.types import BenchmarkResult
from lub.uncertainty.base import get_estimator_cls
from lub.wrappers.hf import HFBackend

OUT = Path(__file__).resolve().parent.parent / "docs" / "tech-report" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)

MODEL = "Qwen/Qwen2.5-0.5B"
SEED = 42

ESTIMATORS = {
    "token_logprob": {},
    "perplexity": {},
    "token_sar": {},
    "self_consistency": {"n_samples": 3, "temperature": 0.7},
}


def main() -> None:
    print(f"Loading {MODEL}...", flush=True)
    backend = HFBackend(model_id=MODEL, device="cpu")

    results: dict[str, BenchmarkResult] = {}

    for name, kwargs in ESTIMATORS.items():
        print(f"\n[{name}] running...", end=" ", flush=True)
        try:
            est = get_estimator_cls(name)(**kwargs)
            pipe = UncertaintyPipeline(backend=backend, estimator=est)
            ds = BrazilianRegulatoryDataset()
            runner = BenchmarkRunner(pipeline=pipe, dataset=ds, results_dir=OUT)
            r = runner.run(seed=SEED, write=False)
            results[name] = r

            path = OUT / f"result_qwen_{name}.json"
            path.write_text(r.model_dump_json(indent=2), encoding="utf-8")

            m = r.metrics
            print(
                f"acc={r.accuracy:.3f}  "
                f"ECE={m.get('ece', 0):.4f}  "
                f"AUROC={m.get('refusal_auroc', 0):.3f}  "
                f"PRR={m.get('prr', 0):.3f}  "
                f"Brier={m.get('brier', 0):.4f}"
            )
        except Exception as e:
            print(f"SKIP ({e})")

    # Print final table
    print("\n" + "=" * 70)
    print("| Estimator | Model | Acc | ECE | AUROC | PRR | Brier | RMSCE |")
    print("|-----------|-------|-----|-----|-------|-----|-------|-------|")
    for name, r in results.items():
        m = r.metrics
        print(
            f"| {name} | Qwen2.5-0.5B | "
            f"{r.accuracy:.3f} | {m.get('ece', 0):.4f} | "
            f"{m.get('refusal_auroc', 0):.3f} | {m.get('prr', 0):.3f} | "
            f"{m.get('brier', 0):.4f} | {m.get('rmsce', 0):.4f} |"
        )

    # Save table
    lines = ["| Estimator | Model | Acc | ECE | AUROC | PRR | Brier | RMSCE |",
             "|-----------|-------|-----|-----|-------|-----|-------|-------|"]
    for name, r in results.items():
        m = r.metrics
        lines.append(
            f"| {name} | Qwen2.5-0.5B | "
            f"{r.accuracy:.3f} | {m.get('ece', 0):.4f} | "
            f"{m.get('refusal_auroc', 0):.3f} | {m.get('prr', 0):.3f} | "
            f"{m.get('brier', 0):.4f} | {m.get('rmsce', 0):.4f} |"
        )
    (OUT / "results_table_qwen.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved to {OUT}/results_table_qwen.md")


if __name__ == "__main__":
    main()
