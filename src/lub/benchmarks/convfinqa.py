# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""ConvFinQA dataset loader."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lub.benchmarks._hf_local import HFLocalDataset
from lub.benchmarks.base import Example
from lub.benchmarks.finqa import _is_numeric

# The original "yale-nlp/convfinqa" repo is gone from the Hub; the maintained
# FinBen mirror ships flat per-turn parquet rows (query / answer / turn).
_HF_PATH = "TheFinAI/flare-convfinqa"


class ConvFinQADataset(HFLocalDataset):
    """ConvFinQA loader filtered to numerical answers."""

    REGISTRY_KEY = "convfinqa"

    def __init__(
        self,
        split: str = "test",
        hf_path: str = _HF_PATH,
        local_path: Path | None = None,
    ) -> None:
        super().__init__(split=split, hf_path=hf_path, local_path=local_path)

    @property
    def name(self) -> str:
        """Return the dataset display name."""
        return "ConvFinQA"

    @property
    def version(self) -> str:
        """Return the dataset version string."""
        return "v1.0"

    def _iter_hf_records(self) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        """Yield flattened per-turn records from the HF dataset.

        Handles both upstream schemas: flare-style rows are already one
        record per turn (``query`` / ``answer`` / ``turn``); the original
        nested rows (``questions`` / ``answers`` lists) are flattened here.
        """
        from datasets import load_dataset

        ds = load_dataset(self.hf_path, split=self.split, revision=self.hf_revision)
        for row_i, row in enumerate(ds):
            row_dict: dict[str, Any] = dict(row)
            if row_dict.get("query"):
                example_id = str(row_dict.get("id") or f"convfinqa-{self.split}-{row_i:06d}")
                rec = {
                    "question": str(row_dict["query"]).strip(),
                    "answer": row_dict.get("answer", ""),
                }
                metadata = {
                    "split": self.split,
                    "turn": row_dict.get("turn", 0),
                    "source": self.hf_path,
                }
                yield example_id, rec, metadata
                continue
            prior = row_dict.get("history") or row_dict.get("dialogue") or []
            questions = row_dict.get("questions") or [row_dict.get("question", "")]
            answers = row_dict.get("answers") or [row_dict.get("answer", "")]
            for t_i, (q, a) in enumerate(zip(questions, answers, strict=False)):
                prefix_turns = list(prior) + list(questions[:t_i])
                prefix = "\n".join(str(x) for x in prefix_turns if x)
                flat_question = f"{prefix}\n{q}".strip() if prefix else str(q).strip()
                synthetic_rec: dict[str, Any] = {
                    "question": flat_question,
                    "answer": a,
                }
                example_id = f"convfinqa-{self.split}-{row_i:06d}-t{t_i}"
                metadata = {"split": self.split, "turn": t_i, "source": self.hf_path}
                yield example_id, synthetic_rec, metadata

    def _build_example(
        self,
        rec: dict[str, Any],
        example_id: str,
        metadata: dict[str, Any],
    ) -> Example | None:
        """Build an Example, skipping non-numeric or empty records."""
        raw_gold = rec.get("gold_answer", rec.get("answer", ""))
        gold = str(raw_gold).strip()
        if not _is_numeric(gold):
            return None
        question = str(rec.get("question", "")).strip()
        if not question:
            return None
        if "turns" not in metadata and "turns" in rec:
            metadata = {**metadata, "turns": rec.get("turns")}
        return Example(
            id=example_id,
            question=question,
            gold_answer=gold,
            metadata=metadata,
        )


__all__ = ["ConvFinQADataset"]
