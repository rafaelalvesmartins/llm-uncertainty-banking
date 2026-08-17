# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared JSONL-backed dataset base class.

Eliminates duplication between credit-scoring, financial-sentiment, and
br_regulatory loaders, which share the same load-from-JSONL-and-yield-Example
logic and differ only in metadata field names.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from lub.benchmarks.base import Dataset, Example, iter_jsonl

_DATA_DIR = Path(__file__).parent / "data"


class JsonlDataset(Dataset):
    """Base for datasets stored as packaged JSONL files.

    Subclasses set class variables; no method overrides needed:

    - ``REGISTRY_KEY`` -- for the auto-registration registry.
    - ``_FILENAME`` -- file name under ``benchmarks/data/``.
    - ``_NAME`` -- stable name for benchmark records.
    - ``_VERSION`` -- dataset version string.
    - ``_METADATA_KEYS`` -- extra JSONL fields to carry in ``Example.metadata``.
    - ``_MISSING_HINT`` -- optional sentence appended to the
      ``FileNotFoundError`` raised by :meth:`load` when the data file
      is absent. Defaults to a pointer to ``data/README.md``;
      ``fetch``-style datasets should override with the script name.
    """

    _FILENAME: ClassVar[str] = ""
    _NAME: ClassVar[str] = ""
    _VERSION: ClassVar[str] = "0.1.0"
    _METADATA_KEYS: ClassVar[tuple[str, ...]] = ()
    _MISSING_HINT: ClassVar[str] = "see benchmarks/data/README.md for provenance."

    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path or (_DATA_DIR / self._FILENAME)

    @property
    def name(self) -> str:
        """Subclass-defined display name (set via ``_NAME`` ClassVar)."""
        return self._NAME

    @property
    def version(self) -> str:
        """Subclass-defined dataset version tag (set via ``_VERSION`` ClassVar)."""
        return self._VERSION

    def load(self) -> Iterator[Example]:
        """Stream examples from the on-disk JSONL file as :class:`Example` rows."""
        if not self.data_path.exists():
            raise FileNotFoundError(
                f"{self._NAME} data file not found at {self.data_path}; {self._MISSING_HINT}"
            )
        for _, record in iter_jsonl(self.data_path):
            metadata = {k: record.get(k, "") for k in self._METADATA_KEYS}
            metadata["source"] = self._NAME
            yield Example(
                id=str(record["id"]),
                question=str(record["question"]),
                gold_answer=str(record["gold_answer"]),
                metadata=metadata,
            )


__all__ = ["JsonlDataset"]
