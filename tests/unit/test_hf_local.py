# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.benchmarks._hf_local.HFLocalDataset.

The base class consolidates the "HuggingFace plus local JSONL fallback"
pattern that TAT-QA, ConvFinQA and similar loaders share. These tests
verify the pluggable hook contract using a tiny in-memory subclass --
no HuggingFace dependency or network access required.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lub.benchmarks._hf_local import HFLocalDataset
from lub.benchmarks.base import Example


class _ToyDataset(HFLocalDataset):
    """Concrete subclass for testing -- no HuggingFace calls."""

    REGISTRY_KEY = "_toy_hf_local_test"

    @property
    def name(self) -> str:
        return "toy"

    @property
    def version(self) -> str:
        return "v0"

    def _build_example(
        self,
        rec: dict[str, Any],
        example_id: str,
        metadata: dict[str, Any],
    ) -> Example | None:
        gold = str(rec.get("answer", "")).strip()
        if not gold:
            return None  # skip
        return Example(
            id=example_id,
            question=str(rec.get("question", "")),
            gold_answer=gold,
            metadata=metadata,
        )

    def _iter_hf_records(
        self,
    ) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        # Stub for the HF path: pretend two records came from upstream.
        yield "hf-1", {"question": "Q1", "answer": "A1"}, {"split": "test", "source": "hf"}
        yield "hf-skip", {"question": "Qskip", "answer": ""}, {"split": "test", "source": "hf"}
        yield "hf-2", {"question": "Q2", "answer": "A2"}, {"split": "test", "source": "hf"}


# ---------------------------------------------------------------------------
# load() routing
# ---------------------------------------------------------------------------

def test_load_uses_hf_path_when_local_path_is_none() -> None:
    ds = _ToyDataset(split="test", hf_path="dummy/dataset", local_path=None)
    examples = list(ds.load())
    # Two records yield Example; one was skipped by _build_example.
    assert [e.id for e in examples] == ["hf-1", "hf-2"]
    assert examples[0].question == "Q1"
    assert examples[0].gold_answer == "A1"
    assert examples[0].metadata == {"split": "test", "source": "hf"}


def test_load_uses_local_path_when_set(tmp_path: Path) -> None:
    jsonl = tmp_path / "toy.jsonl"
    jsonl.write_text(
        "\n".join([
            json.dumps({"id": "L1", "question": "Q1", "answer": "A1"}),
            json.dumps({"id": "L2", "question": "Q2", "answer": "A2"}),
        ]),
        encoding="utf-8",
    )
    ds = _ToyDataset(split="test", hf_path="dummy/dataset", local_path=jsonl)
    examples = list(ds.load())
    assert [e.id for e in examples] == ["L1", "L2"]
    assert examples[0].metadata == {"source": "local"}


def test_local_path_synthesises_id_when_record_lacks_one(tmp_path: Path) -> None:
    """A malformed JSONL without ``id`` / ``uid`` should still load; the
    base class synthesises ``<key>-local-line<n>`` so callers see a
    usable id rather than a KeyError."""
    jsonl = tmp_path / "noid.jsonl"
    jsonl.write_text(
        json.dumps({"question": "Q1", "answer": "A1"}) + "\n", encoding="utf-8",
    )
    ds = _ToyDataset(split="test", hf_path="x", local_path=jsonl)
    examples = list(ds.load())
    assert len(examples) == 1
    assert examples[0].id.startswith(f"{_ToyDataset.REGISTRY_KEY}-local-line")


def test_build_example_returning_none_skips_record() -> None:
    """The toy ``_build_example`` returns None for empty answers; verify
    the framework drops those records cleanly rather than emitting a
    placeholder."""
    ds = _ToyDataset(split="test", hf_path="x", local_path=None)
    examples = list(ds.load())
    assert "hf-skip" not in {e.id for e in examples}


def test_iter_local_requires_local_path_to_be_set() -> None:
    """Calling _iter_local_records without local_path is a programming
    error -- the assert fires loud."""
    ds = _ToyDataset(split="test", hf_path="x", local_path=None)
    with pytest.raises(AssertionError):
        list(ds._iter_local_records())


def test_subclass_auto_registers_via_init_subclass() -> None:
    """The Dataset base uses ``__init_subclass__`` for auto-registration;
    HFLocalDataset must not break that."""
    from lub.benchmarks.base import Dataset
    assert "_toy_hf_local_test" in Dataset._registry
    assert Dataset._registry["_toy_hf_local_test"] is _ToyDataset
