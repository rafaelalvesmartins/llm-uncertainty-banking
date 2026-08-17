#!/usr/bin/env python3
# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Materialize the FLARE-sourced benchmark JSONL files under benchmarks/data/.

The four classification loaders that LUB ships
(:class:`lub.benchmarks.financial_sentiment.FPBDataset`,
:class:`~lub.benchmarks.financial_sentiment.FiQASADataset`,
:class:`~lub.benchmarks.credit_scoring.GermanCreditDataset`,
:class:`~lub.benchmarks.credit_scoring.AustralianCreditDataset`) all expect
a packaged JSONL file under
``src/lub/benchmarks/data/``. This script pulls the matching FLARE variant
from HuggingFace, normalizes each row into LUB's ``Example`` schema, and
writes the JSONL. Running it is a one-time step per LUB checkout.

Usage::

    python scripts/fetch_flare_datasets.py                 # all four
    python scripts/fetch_flare_datasets.py --only fpb      # one task
    python scripts/fetch_flare_datasets.py --split test    # override split
    python scripts/fetch_flare_datasets.py --limit 200     # sample first N

The script is idempotent: it rewrites the JSONL on each run, preserving
the row order that HuggingFace returns. Licensing for each upstream
dataset is recorded in the written header — callers should verify the
license permits their intended use before publishing derived results.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FlareTask:
    """Declarative spec for one FLARE-derived dataset."""

    lub_name: str
    hf_path: str
    hf_split: str
    out_filename: str
    license: str
    extra_metadata_keys: tuple[str, ...]


_TASKS: tuple[FlareTask, ...] = (
    FlareTask(
        lub_name="fpb",
        hf_path="TheFinAI/flare-fpb",
        hf_split="test",
        out_filename="fpb.jsonl",
        license="CC-BY-NC-SA 3.0 (Malo et al. 2014)",
        extra_metadata_keys=("aspect",),
    ),
    FlareTask(
        lub_name="fiqa_sa",
        hf_path="TheFinAI/flare-fiqasa",
        hf_split="test",
        out_filename="fiqa_sa.jsonl",
        license="Public — WWW'18 FiQA challenge",
        extra_metadata_keys=("aspect",),
    ),
    FlareTask(
        lub_name="german_credit",
        hf_path="TheFinAI/flare-german",
        hf_split="test",
        out_filename="german_credit.jsonl",
        license="UCI ML Repository — CC-BY 4.0",
        extra_metadata_keys=("label",),
    ),
    FlareTask(
        lub_name="australian_credit",
        hf_path="TheFinAI/flare-australian",
        hf_split="test",
        out_filename="australian_credit.jsonl",
        license="UCI ML Repository — CC-BY 4.0",
        extra_metadata_keys=("label",),
    ),
)

_DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "lub" / "benchmarks" / "data"


def _row_to_record(task: FlareTask, index: int, row: dict[str, Any]) -> dict[str, Any]:
    """Map a FLARE-style HF row to LUB's ``Example`` JSONL schema.

    FLARE datasets expose at minimum ``query``, ``answer``, and ``choices``.
    Some variants also carry ``label`` (numeric class index) or ``aspect``
    (FiQA-SA target phrase). We pass those through into ``metadata``.
    """
    question = row.get("query") or row.get("text") or row.get("question")
    if not question:
        raise KeyError(
            f"{task.hf_path} row {index} is missing a question field "
            f"(expected one of: query / text / question)"
        )
    answer = row.get("answer") or row.get("label") or row.get("gold")
    if answer is None:
        raise KeyError(
            f"{task.hf_path} row {index} is missing a gold-answer field"
        )
    record: dict[str, Any] = {
        "id": str(row.get("id", f"{task.lub_name}-{index:05d}")),
        "question": str(question).strip(),
        "gold_answer": str(answer).strip(),
    }
    for key in task.extra_metadata_keys:
        if key in row:
            record[key] = row[key]
    return record


def _load_task(task: FlareTask, split: str, limit: int | None) -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover - handled by user-friendly msg
        raise SystemExit(
            "fetch_flare_datasets.py requires 'datasets'. "
            "Install with: pip install 'llm-uncertainty-banking[dev]'"
        ) from exc

    print(f"[fetch] loading {task.hf_path} split={split} ...", file=sys.stderr)
    ds = load_dataset(task.hf_path, split=split)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(ds):
        if limit is not None and index >= limit:
            break
        records.append(_row_to_record(task, index, dict(row)))
    return records


def _write_jsonl(task: FlareTask, records: list[dict[str, Any]]) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / task.out_filename
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            f"# Source: HuggingFace {task.hf_path}\n"
            f"# License: {task.license}\n"
            f"# n={len(records)} — regenerate via scripts/fetch_flare_datasets.py\n"
        )
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(
        f"[fetch] wrote {out.relative_to(_DATA_DIR.parent.parent.parent.parent)} "
        f"({len(records)} rows, license={task.license})",
        file=sys.stderr,
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize FLARE-sourced benchmark JSONL files."
    )
    parser.add_argument(
        "--only",
        choices=[t.lub_name for t in _TASKS],
        action="append",
        help="Fetch only the named task (repeatable). Default: all four.",
    )
    parser.add_argument(
        "--split",
        default=None,
        help="Override HuggingFace split (default: each task's test split).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Sample the first N rows instead of the full split.",
    )
    args = parser.parse_args()

    names = set(args.only) if args.only else {t.lub_name for t in _TASKS}
    for task in _TASKS:
        if task.lub_name not in names:
            continue
        split = args.split or task.hf_split
        records = _load_task(task, split=split, limit=args.limit)
        _write_jsonl(task, records)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
