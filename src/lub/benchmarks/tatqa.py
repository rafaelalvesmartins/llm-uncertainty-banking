# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""TAT-QA dataset loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lub.benchmarks._hf_local import HFLocalDataset
from lub.benchmarks.base import Example
from lub.benchmarks.finqa import _is_numeric

# The official "next-tat/tat-qa" repo ships raw nested JSON that the datasets
# auto-converter cannot turn into Arrow (mixed list / non-list columns). The
# maintained FinBen mirror ships flat parquet rows (query / answer / text),
# where ``query`` already embeds the table + paragraphs + question.
_HF_PATH = "TheFinAI/flare-tatqa"


def _serialize_table(table: Any) -> str:
    """Render a TAT-QA table (list-of-rows) as a markdown code block."""
    if not table:
        return ""
    rows = (table.get("table") or table.get("rows") or []) if isinstance(table, dict) else table
    if not rows:
        return ""
    lines = ["```", *[" | ".join(str(c) for c in row) for row in rows], "```"]
    return "\n".join(lines)


def _extract_answer(row: dict[str, Any]) -> str:
    """Extract the single gold answer string from a TAT-QA row."""
    ans = row.get("answer")
    if isinstance(ans, list):
        if len(ans) != 1:
            return ""
        return str(ans[0]).strip()
    if ans is None:
        return ""
    return str(ans).strip()


_NUMERIC_TYPES = {"arithmetic", "number"}
_SUPPORTED_TYPES = {"span", *_NUMERIC_TYPES}


def _is_supported(row: dict[str, Any], gold: str) -> bool:
    """Return True when the row's answer type is supported by the loader."""
    answer_type = (row.get("answer_type") or row.get("type") or "").lower()
    if answer_type and answer_type not in _SUPPORTED_TYPES:
        return False
    return not (answer_type in _NUMERIC_TYPES and not _is_numeric(gold))


class TATQADataset(HFLocalDataset):
    """TAT-QA loader with table-to-markdown serialization."""

    REGISTRY_KEY = "tatqa"

    def __init__(
        self,
        split: str = "test",
        hf_path: str = _HF_PATH,
        local_path: Path | None = None,
    ) -> None:
        """Initialize the TAT-QA loader for the given split and source path.

        The default split is ``test`` — the only split the flare mirror ships
        (the previous ``dev`` default targeted the raw repo, which no longer
        loads under ``datasets`` >= 3).
        """
        super().__init__(split=split, hf_path=hf_path, local_path=local_path)

    @property
    def name(self) -> str:
        """Return the human-readable dataset name."""
        return "TAT-QA"

    @property
    def version(self) -> str:
        """Return the dataset version string."""
        return "v1.0"

    def _build_example(
        self,
        rec: dict[str, Any],
        example_id: str,
        metadata: dict[str, Any],
    ) -> Example | None:
        """Convert a raw TAT-QA record into an Example, or None if unsupported."""
        gold = _extract_answer(rec)
        if not gold or not _is_supported(rec, gold):
            return None
        if "answer_type" not in metadata and rec.get("answer_type"):
            metadata = {**metadata, "answer_type": rec.get("answer_type")}
        query = str(rec.get("query") or "").strip()
        if query:
            # Flare-style flat record: ``query`` already embeds the table,
            # paragraphs, and question — use it as the full prompt.
            return Example(id=example_id, question=query, gold_answer=gold, metadata=metadata)
        table_md = _serialize_table(rec.get("table"))
        paragraphs = rec.get("paragraphs") or rec.get("text") or ""
        if isinstance(paragraphs, list):
            paragraphs = "\n".join(str(p) for p in paragraphs)
        question = str(rec.get("question", "")).strip()
        full = "\n\n".join(p for p in (table_md, str(paragraphs), question) if p)
        if not full:
            return None
        return Example(id=example_id, question=full, gold_answer=gold, metadata=metadata)


__all__ = ["TATQADataset"]
