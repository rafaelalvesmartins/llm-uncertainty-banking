# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Evaluate a cascaded Tiered Router on br_regulatory.jsonl.

Usage
-----
    python benchmarks/scripts/run_cascaded_router.py \
        --dataset src/lub/benchmarks/data/br_regulatory.jsonl \
        --out benchmarks/results/cascaded/run.json

Runs each prompt through the DummyBackend at two tiers (stand-ins for
Haiku and Sonnet) and records the cascaded result. Replace the two
pipelines with real Anthropic backends to produce the v0.2 figure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lub.orchestration import Tier, TieredRouter
from lub.pipeline import UncertaintyPipeline


def build_router() -> TieredRouter:
    cheap = UncertaintyPipeline.from_pretrained(
        model="dummy-haiku", backend="dummy", estimator="token_logprob"
    )
    strong = UncertaintyPipeline.from_pretrained(
        model="dummy-sonnet", backend="dummy", estimator="p_true"
    )
    return TieredRouter(
        tiers=[
            Tier("haiku", cheap, threshold=0.80, cost=0.001),
            Tier("sonnet", strong, threshold=0.70, cost=0.015),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    router = build_router()
    rows: list[dict] = []
    with args.dataset.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if args.limit is not None and i >= args.limit:
                break
            ex = json.loads(line)
            prompt = ex.get("prompt") or ex.get("question") or ""
            routed = router.answer(prompt)
            rows.append(
                {
                    "prompt": prompt,
                    "routed": routed.to_dict(),
                    "ground_truth": ex.get("answer"),
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "router": {"tiers": [t.name for t in router.tiers]},
                "rows": rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
