# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared base class for "HuggingFace plus local JSONL fallback" datasets."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lub.benchmarks.base import Dataset, Example, iter_jsonl


class HFLocalDataset(Dataset):
    """Abstract base for HuggingFace-with-local-fallback dataset loaders.

    Subclasses must define ``REGISTRY_KEY``, ``name``, ``version`` (from
    :class:`Dataset`) and implement :meth:`_build_example`. They may
    optionally override :meth:`_iter_hf_records` when upstream rows
    expand to multiple :class:`Example` records.
    """

    def __init__(
        self,
        split: str,
        hf_path: str,
        local_path: Path | None = None,
        hf_revision: str | None = None,
    ) -> None:
        """Construct.

        Args:
            split: Dataset split (e.g. "train", "validation").
            hf_path: HuggingFace dataset path (e.g. "openai/gsm8k").
            local_path: Optional local cache path; when set, bypass HF.
            hf_revision: Pin the dataset to a specific commit/tag/branch.
                Strongly recommended for reproducible/auditable runs;
                None defaults to the dataset's main branch (latest).
        """
        self.split = split
        self.hf_path = hf_path
        self.local_path = local_path
        self.hf_revision = hf_revision

    @abstractmethod
    def _build_example(
        self,
        rec: dict[str, Any],
        example_id: str,
        metadata: dict[str, Any],
    ) -> Example | None:
        """Build an Example from one record. Return None to skip."""

    def _iter_hf_records(self) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        from datasets import load_dataset

        ds = load_dataset(self.hf_path, split=self.split, revision=self.hf_revision)
        key = self.REGISTRY_KEY or type(self).__name__.lower()
        for i, row in enumerate(ds):
            rec: dict[str, Any] = dict(row)
            example_id = str(rec.get("uid") or rec.get("id") or f"{key}-{self.split}-{i:06d}")
            yield example_id, rec, {"split": self.split, "source": self.hf_path}

    def _iter_local_records(self) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        assert self.local_path is not None, "_iter_local_records called without local_path set"
        key = self.REGISTRY_KEY or type(self).__name__.lower()
        for line_no, rec in iter_jsonl(self.local_path):
            example_id = str(rec.get("id") or rec.get("uid") or f"{key}-local-line{line_no:06d}")
            yield example_id, rec, {"source": "local"}

    def load(self) -> Iterator[Example]:
        """Load the dataset from the configured source."""
        records = (
            self._iter_local_records() if self.local_path is not None else self._iter_hf_records()
        )
        for example_id, rec, metadata in records:
            example = self._build_example(rec, example_id, metadata)
            if example is not None:
                yield example


__all__ = ["HFLocalDataset"]
