#!/usr/bin/env python3
"""Reproducible real-model benchmark (planning/39 P1).

Runs br_regulatory through a real local LLM (Ollama, via the openai backend +
OPENAI_BASE_URL) with the `perplexity` estimator and `fuzzy_match` correctness —
the non-degenerate configuration. `self_consistency` over-refuses on open-ended
answers (no answer normalization); `exact_match` scores verbose answers as wrong
even when they contain the gold value, so extractive containment is the honest
scorer here. The CLI does not yet expose a correctness override, hence this script.

    ollama serve            # (or have Ollama running on :11434)
    ollama pull llama3.1:8b
    python scripts/run_real_benchmark.py --model llama3.1:8b --limit 20
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("LUB_OPENAI_API_KEY", "ollama")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="llama3.1:8b")
    ap.add_argument("--dataset", default="br_regulatory")
    ap.add_argument("--estimator", default="perplexity")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from lub.benchmarks.correctness import fuzzy_match
    from lub.benchmarks.runner import BenchmarkRunner
    from lub.cli.benchmark import _resolve_dataset
    from lub.pipeline import UncertaintyPipeline

    pipe = UncertaintyPipeline.from_pretrained(
        model=args.model, backend="openai", estimator=args.estimator
    )
    runner = BenchmarkRunner(
        pipeline=pipe,
        dataset=_resolve_dataset(args.dataset),
        correctness_fn=fuzzy_match,
        results_dir=_ROOT / "benchmarks" / "results",
    )
    rec = runner.run(limit=args.limit, seed=args.seed)
    d = rec.model_dump()
    print("=== real-model benchmark result ===")
    for k in ("dataset", "backend", "estimator", "n", "accuracy", "refusal_auroc", "ece"):
        print(f"  {k}: {d.get(k)}")


if __name__ == "__main__":
    main()
