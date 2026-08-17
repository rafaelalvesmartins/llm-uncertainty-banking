# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""FinQA loader.

FinQA (Chen et al. 2021) is a numerical reasoning QA dataset over financial
reports. We load it via the HuggingFace ``datasets`` library, normalize
every record to the library-wide :class:`~lub.benchmarks.base.Example`
schema, and filter to examples whose gold answer parses as a number so
that downstream scorers can compare answers numerically.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lub.benchmarks.base import Dataset, Example

_FINQA_HF_PATH = "dreamerdeo/finqa"
# The upstream repo is a script-based dataset; ``datasets`` >= 3.0 no longer
# executes dataset scripts, so we default to the Hub's auto-converted parquet
# branch, which preserves the original fields (question / answer / id / ...).
_FINQA_HF_REVISION = "refs/convert/parquet"


def _is_numeric(text: str) -> bool:
    cleaned = text.strip().replace(",", "").replace("%", "").replace("$", "")
    if cleaned.startswith(("(", "-")):
        cleaned = cleaned.lstrip("(-")
        cleaned = cleaned.rstrip(")")
    if not cleaned:
        return False
    try:
        float(cleaned)
    except ValueError:
        return False
    return True


class FinQADataset(Dataset):
    """HuggingFace FinQA loader filtered to numerical answers."""

    REGISTRY_KEY = "finqa"

    def __init__(
        self,
        split: str = "test",
        hf_path: str = _FINQA_HF_PATH,
        hf_revision: str | None = _FINQA_HF_REVISION,
    ) -> None:
        self.split = split
        self.hf_path = hf_path
        self.hf_revision = hf_revision

    @property
    def name(self) -> str:
        """Return the registry key for this dataset."""
        return "finqa"

    @property
    def version(self) -> str:
        """Return a version string identifying the HF path and split."""
        return f"{self.hf_path}:{self.split}"

    def load(self) -> Iterator[Example]:
        """Yield numeric-answer examples from the FinQA HuggingFace split."""
        from datasets import load_dataset

        ds = load_dataset(self.hf_path, split=self.split, revision=self.hf_revision)
        for i, row in enumerate(ds):
            row_dict: dict[str, Any] = dict(row)
            gold = str(
                row_dict.get("answer")
                or row_dict.get("final_result")
                or row_dict.get("exe_ans")
                or ""
            ).strip()
            if not _is_numeric(gold):
                continue
            question = str(row_dict.get("question", "")).strip()
            if not question:
                continue
            example_id = str(row_dict.get("id") or f"finqa-{self.split}-{i:06d}")
            yield Example(
                id=example_id,
                question=question,
                gold_answer=gold,
                metadata={"split": self.split, "source": self.hf_path},
            )


__all__ = ["FinQADataset"]
