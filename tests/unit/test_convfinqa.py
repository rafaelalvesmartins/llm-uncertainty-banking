# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.benchmarks.convfinqa`.

These tests exercise the multi-turn flattening logic, the numeric filter,
metadata propagation and the registry registration of
:class:`ConvFinQADataset`. The HuggingFace ``datasets`` library is
patched out so the tests run without network access.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.convfinqa import ConvFinQADataset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_fake_datasets(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    """Install a fake ``datasets`` module that yields *rows* from load_dataset."""

    def fake_load_dataset(
        path: str, split: str = "test", revision: str | None = None
    ) -> list[dict[str, Any]]:
        return rows

    fake_mod = ModuleType("datasets")
    fake_mod.load_dataset = fake_load_dataset  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", fake_mod)


# ---------------------------------------------------------------------------
# Properties / construction
# ---------------------------------------------------------------------------


def test_name_property_returns_display_name() -> None:
    ds = ConvFinQADataset()
    assert ds.name == "ConvFinQA"


def test_version_property_returns_v1_0() -> None:
    ds = ConvFinQADataset()
    assert ds.version == "v1.0"


def test_default_constructor_uses_test_split_and_default_hf_path() -> None:
    ds = ConvFinQADataset()
    assert ds.split == "test"
    assert ds.hf_path == "TheFinAI/flare-convfinqa"
    assert ds.local_path is None


def test_constructor_overrides_propagate() -> None:
    ds = ConvFinQADataset(split="train", hf_path="custom/path", local_path=None)
    assert ds.split == "train"
    assert ds.hf_path == "custom/path"


def test_subclass_is_registered_under_convfinqa_key() -> None:
    assert "convfinqa" in Dataset._registry
    assert Dataset._registry["convfinqa"] is ConvFinQADataset


# ---------------------------------------------------------------------------
# _build_example
# ---------------------------------------------------------------------------


def test_build_example_returns_example_for_numeric_answer() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "What is 2+2?", "answer": "4"},
        example_id="convfinqa-test-000000-t0",
        metadata={"split": "test", "turn": 0, "source": "x"},
    )
    assert ex is not None
    assert isinstance(ex, Example)
    assert ex.id == "convfinqa-test-000000-t0"
    assert ex.question == "What is 2+2?"
    assert ex.gold_answer == "4"
    assert ex.metadata == {"split": "test", "turn": 0, "source": "x"}


def test_build_example_prefers_gold_answer_over_answer() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "q", "gold_answer": "42", "answer": "wrong"},
        example_id="id-1",
        metadata={},
    )
    assert ex is not None
    assert ex.gold_answer == "42"


def test_build_example_returns_none_for_non_numeric_answer() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "q", "answer": "increased significantly"},
        example_id="id-1",
        metadata={},
    )
    assert ex is None


def test_build_example_returns_none_for_empty_question() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "   ", "answer": "12.5"},
        example_id="id-1",
        metadata={},
    )
    assert ex is None


def test_build_example_returns_none_for_missing_answer() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "q"},
        example_id="id-1",
        metadata={},
    )
    assert ex is None


def test_build_example_strips_whitespace_in_question_and_answer() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "  what?  ", "answer": "  3.14  "},
        example_id="id-1",
        metadata={},
    )
    assert ex is not None
    assert ex.question == "what?"
    assert ex.gold_answer == "3.14"


def test_build_example_accepts_currency_and_percent_answers() -> None:
    ds = ConvFinQADataset()
    for ans in ["$1,200", "12%", "(3.5)", "-7"]:
        ex = ds._build_example(
            rec={"question": "q", "answer": ans},
            example_id="id-1",
            metadata={},
        )
        assert ex is not None, f"expected numeric: {ans!r}"


def test_build_example_merges_turns_field_into_metadata() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "q", "answer": "1", "turns": 3},
        example_id="id-1",
        metadata={"split": "test"},
    )
    assert ex is not None
    assert ex.metadata == {"split": "test", "turns": 3}


def test_build_example_does_not_overwrite_existing_turns_metadata() -> None:
    ds = ConvFinQADataset()
    ex = ds._build_example(
        rec={"question": "q", "answer": "1", "turns": 99},
        example_id="id-1",
        metadata={"split": "test", "turns": 7},
    )
    assert ex is not None
    assert ex.metadata["turns"] == 7


# ---------------------------------------------------------------------------
# _iter_hf_records: flattening multi-turn dialogues
# ---------------------------------------------------------------------------


def test_iter_hf_records_flattens_single_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"question": "Q only", "answer": "1"}],
    )
    ds = ConvFinQADataset(split="test")
    records = list(ds._iter_hf_records())
    assert len(records) == 1
    example_id, rec, metadata = records[0]
    assert example_id == "convfinqa-test-000000-t0"
    assert rec["question"] == "Q only"
    assert rec["answer"] == "1"
    assert metadata == {"split": "test", "turn": 0, "source": "TheFinAI/flare-convfinqa"}


def test_iter_hf_records_flattens_multi_turn_dialogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """For a row with N questions, the iterator yields N records and prefixes
    each later turn with all earlier questions joined by newlines."""
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {
                "questions": ["What was revenue?", "What was the growth?"],
                "answers": ["100", "0.1"],
            }
        ],
    )
    ds = ConvFinQADataset(split="test")
    records = list(ds._iter_hf_records())

    assert len(records) == 2

    id0, rec0, meta0 = records[0]
    assert id0 == "convfinqa-test-000000-t0"
    assert rec0["question"] == "What was revenue?"
    assert rec0["answer"] == "100"
    assert meta0["turn"] == 0

    id1, rec1, meta1 = records[1]
    assert id1 == "convfinqa-test-000000-t1"
    assert rec1["question"] == "What was revenue?\nWhat was the growth?"
    assert rec1["answer"] == "0.1"
    assert meta1["turn"] == 1


def test_iter_hf_records_includes_history_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the row has a ``history`` field, it should be prefixed to every
    turn's flattened question."""
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {
                "history": ["Prior context line A", "Prior context line B"],
                "questions": ["Now?"],
                "answers": ["42"],
            }
        ],
    )
    ds = ConvFinQADataset(split="test")
    records = list(ds._iter_hf_records())
    assert len(records) == 1
    _, rec, _ = records[0]
    assert rec["question"] == "Prior context line A\nPrior context line B\nNow?"


def test_iter_hf_records_uses_dialogue_when_history_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dialogue`` is accepted as an alias for ``history``."""
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {
                "dialogue": ["earlier turn"],
                "questions": ["latest?"],
                "answers": ["7"],
            }
        ],
    )
    ds = ConvFinQADataset(split="test")
    records = list(ds._iter_hf_records())
    assert len(records) == 1
    _, rec, _ = records[0]
    assert rec["question"] == "earlier turn\nlatest?"


def test_iter_hf_records_assigns_unique_row_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"question": "Q1", "answer": "1"},
            {"question": "Q2", "answer": "2"},
        ],
    )
    ds = ConvFinQADataset(split="test")
    ids = [rec_id for rec_id, _, _ in ds._iter_hf_records()]
    assert ids == ["convfinqa-test-000000-t0", "convfinqa-test-000001-t0"]


def test_iter_hf_records_falls_back_to_singular_question_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows lacking ``questions``/``answers`` should fall back to singular
    ``question``/``answer`` fields."""
    _install_fake_datasets(
        monkeypatch,
        rows=[{"question": "single Q", "answer": "single A"}],
    )
    ds = ConvFinQADataset(split="test")
    records = list(ds._iter_hf_records())
    assert len(records) == 1
    _, rec, _ = records[0]
    assert rec["question"] == "single Q"
    assert rec["answer"] == "single A"


def test_iter_hf_records_metadata_source_matches_hf_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(monkeypatch, rows=[{"question": "Q", "answer": "1"}])
    ds = ConvFinQADataset(split="train", hf_path="custom/path")
    _, _, metadata = next(iter(ds._iter_hf_records()))
    assert metadata["split"] == "train"
    assert metadata["source"] == "custom/path"


# ---------------------------------------------------------------------------
# Integration via load() — combines _iter_hf_records and _build_example
# ---------------------------------------------------------------------------


def test_load_yields_only_numeric_examples_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"question": "Q num", "answer": "10"},
            {"question": "Q text", "answer": "increased"},
            {"question": "", "answer": "3"},
        ],
    )
    ds = ConvFinQADataset(split="test")
    examples = list(ds.load())
    assert len(examples) == 1
    assert examples[0].question == "Q num"
    assert examples[0].gold_answer == "10"


def test_load_returns_iterator_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(monkeypatch, rows=[{"question": "Q", "answer": "1"}])
    ds = ConvFinQADataset(split="test")
    result = ds.load()
    assert not isinstance(result, list)
    assert hasattr(result, "__next__")


def test_load_uses_local_path_when_provided(tmp_path: Any) -> None:
    """When local_path is set, load() should bypass the HF iterator entirely
    -- so we can omit a fake ``datasets`` module without ImportError."""
    import json

    jsonl = tmp_path / "convfinqa.jsonl"
    jsonl.write_text(
        json.dumps({"id": "rec-1", "question": "Q1", "answer": "9.5"}) + "\n",
        encoding="utf-8",
    )
    ds = ConvFinQADataset(split="test", local_path=jsonl)
    examples = list(ds.load())
    assert len(examples) == 1
    assert examples[0].id == "rec-1"
    assert examples[0].gold_answer == "9.5"
    assert examples[0].metadata == {"source": "local"}


# ---------------------------------------------------------------------------
# Dataset registry lookup
# ---------------------------------------------------------------------------


def test_registry_lookup_returns_convfinqa_class() -> None:
    cls = Dataset.get_dataset_cls("convfinqa")
    assert cls is ConvFinQADataset


def test_list_datasets_includes_convfinqa() -> None:
    assert "convfinqa" in Dataset.list_datasets()
