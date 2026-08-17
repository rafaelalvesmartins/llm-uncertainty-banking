# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.benchmarks.financial_sentiment`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.financial_sentiment import FiQASADataset, FPBDataset

_CLASSES = [
    (FPBDataset, "fpb", "fpb.jsonl"),
    (FiQASADataset, "fiqa_sa", "fiqa_sa.jsonl"),
]


@pytest.fixture
def fpb_records() -> list[dict[str, object]]:
    """Three well-formed JSONL records spanning the FPB 3-class label set."""
    return [
        {
            "id": "fpb-001",
            "question": (
                "What is the sentiment of: "
                "'Operating profit rose to EUR 13.1 mn from EUR 8.7 mn'? "
                "Answer positive / negative / neutral."
            ),
            "gold_answer": "positive",
            "aspect": "earnings",
        },
        {
            "id": "fpb-002",
            "question": (
                "What is the sentiment of: "
                "'The company slipped to a pretax loss of EUR 2.4 mn'? "
                "Answer positive / negative / neutral."
            ),
            "gold_answer": "negative",
            "aspect": "earnings",
        },
        {
            "id": "fpb-003",
            "question": (
                "What is the sentiment of: "
                "'The board will meet on March 14 to discuss the dividend'? "
                "Answer positive / negative / neutral."
            ),
            "gold_answer": "neutral",
            "aspect": "governance",
        },
    ]


@pytest.fixture
def fiqa_records() -> list[dict[str, object]]:
    """Two well-formed JSONL records matching the FiQA-SA schema."""
    return [
        {
            "id": "fiqa-001",
            "question": (
                "Sentiment of microblog post about $AAPL guidance? "
                "Answer positive / negative / neutral."
            ),
            "gold_answer": "positive",
            "aspect": "stock/guidance",
        },
        {
            "id": "fiqa-002",
            "question": (
                "Sentiment of headline on rising default rates? "
                "Answer positive / negative / neutral."
            ),
            "gold_answer": "negative",
            "aspect": "credit/default",
        },
    ]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


@pytest.fixture
def fpb_jsonl(tmp_path: Path, fpb_records: list[dict[str, object]]) -> Path:
    return _write_jsonl(tmp_path / "fpb.jsonl", fpb_records)


@pytest.fixture
def fiqa_jsonl(tmp_path: Path, fiqa_records: list[dict[str, object]]) -> Path:
    return _write_jsonl(tmp_path / "fiqa_sa.jsonl", fiqa_records)


@pytest.mark.parametrize("cls, expected_name, filename", _CLASSES)
def test_class_attributes_are_wired(
    cls: type, expected_name: str, filename: str
) -> None:
    """Each dataset exposes the documented class-level attributes."""
    assert cls.REGISTRY_KEY == expected_name
    assert cls._NAME == expected_name
    assert cls._FILENAME == filename
    assert cls._METADATA_KEYS == ("aspect",)


@pytest.mark.parametrize("cls, expected_name, filename", _CLASSES)
def test_instance_is_a_dataset(cls: type, expected_name: str, filename: str) -> None:
    """Instances satisfy the abstract :class:`Dataset` contract."""
    ds = cls()
    assert isinstance(ds, Dataset)
    assert ds.name == expected_name
    parts = ds.version.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


@pytest.mark.parametrize("cls, expected_name, filename", _CLASSES)
def test_auto_registration(cls: type, expected_name: str, filename: str) -> None:
    """Importing the module registers each dataset under its key."""
    assert Dataset.get_dataset_cls(expected_name) is cls


@pytest.mark.parametrize("cls, expected_name, filename", _CLASSES)
def test_default_data_path_points_inside_package(
    cls: type, expected_name: str, filename: str
) -> None:
    """Default ``data_path`` resolves to the packaged ``benchmarks/data`` dir."""
    ds = cls()
    assert ds.data_path.name == filename
    assert ds.data_path.parent.name == "data"


@pytest.mark.parametrize("cls, expected_name, filename", _CLASSES)
def test_load_raises_when_data_file_missing(
    cls: type, expected_name: str, filename: str, tmp_path: Path
) -> None:
    """Missing JSONL file raises ``FileNotFoundError`` with the name in it."""
    missing = tmp_path / "does_not_exist.jsonl"
    ds = cls(data_path=missing)
    with pytest.raises(FileNotFoundError) as excinfo:
        list(ds.load())
    assert expected_name in str(excinfo.value)


def test_fpb_loads_three_class_examples(fpb_jsonl: Path) -> None:
    """FPBDataset parses JSONL into Example tuples covering all 3 classes."""
    ds = FPBDataset(data_path=fpb_jsonl)
    examples = list(ds.load())
    assert len(examples) == 3
    assert all(isinstance(ex, Example) for ex in examples)
    labels = {ex.gold_answer for ex in examples}
    assert labels == {"positive", "negative", "neutral"}
    assert examples[0].id == "fpb-001"


def test_fpb_metadata_carries_aspect_and_source(fpb_jsonl: Path) -> None:
    """``aspect`` is preserved verbatim and ``source`` is set to the dataset name."""
    ds = FPBDataset(data_path=fpb_jsonl)
    examples = list(ds.load())
    assert examples[0].metadata["aspect"] == "earnings"
    assert examples[2].metadata["aspect"] == "governance"
    assert all(ex.metadata["source"] == "fpb" for ex in examples)


def test_fiqa_loads_examples(fiqa_jsonl: Path) -> None:
    """FiQASADataset parses JSONL records into Example tuples."""
    ds = FiQASADataset(data_path=fiqa_jsonl)
    examples = list(ds.load())
    assert len(examples) == 2
    assert examples[0].id == "fiqa-001"
    assert examples[0].gold_answer == "positive"
    assert examples[1].gold_answer == "negative"


def test_fiqa_metadata_carries_aspect_and_source(fiqa_jsonl: Path) -> None:
    """FiQA aspect strings and source tag survive the round trip."""
    ds = FiQASADataset(data_path=fiqa_jsonl)
    examples = list(ds.load())
    assert examples[0].metadata["aspect"] == "stock/guidance"
    assert examples[1].metadata["aspect"] == "credit/default"
    assert all(ex.metadata["source"] == "fiqa_sa" for ex in examples)


def test_load_is_lazy_iterator(fpb_jsonl: Path) -> None:
    """``load`` returns an iterator, not a pre-materialized list."""
    ds = FPBDataset(data_path=fpb_jsonl)
    it = ds.load()
    assert iter(it) is it
    first = next(it)
    assert first.id == "fpb-001"


def test_missing_aspect_field_defaults_to_empty_string(tmp_path: Path) -> None:
    """Records without an ``aspect`` field load with ``aspect=""`` (no crash)."""
    record = {
        "id": "fpb-noaspect",
        "question": "Sentiment of: 'profit unchanged'? positive / negative / neutral.",
        "gold_answer": "neutral",
    }
    path = _write_jsonl(tmp_path / "fpb.jsonl", [record])
    ds = FPBDataset(data_path=path)
    [ex] = list(ds.load())
    assert ex.metadata["aspect"] == ""
    assert ex.metadata["source"] == "fpb"


def test_validate_passes_on_well_formed_records(fpb_jsonl: Path) -> None:
    """``validate`` returns an empty list for clean JSONL."""
    ds = FPBDataset(data_path=fpb_jsonl)
    assert ds.validate() == []


def test_validate_flags_blank_question(
    tmp_path: Path, fpb_records: list[dict[str, object]]
) -> None:
    """``validate`` flags rows with a blank ``question`` field."""
    fpb_records[0]["question"] = "   "
    path = _write_jsonl(tmp_path / "bad.jsonl", fpb_records)
    ds = FPBDataset(data_path=path)
    warnings = ds.validate()
    assert any("question is blank" in w for w in warnings)


def test_validate_flags_blank_gold_answer(
    tmp_path: Path, fiqa_records: list[dict[str, object]]
) -> None:
    """``validate`` flags rows whose ``gold_answer`` is blank."""
    fiqa_records[1]["gold_answer"] = ""
    path = _write_jsonl(tmp_path / "bad.jsonl", fiqa_records)
    ds = FiQASADataset(data_path=path)
    warnings = ds.validate()
    assert any("gold_answer is blank" in w for w in warnings)


def test_malformed_json_raises_value_error_with_line_number(tmp_path: Path) -> None:
    """A line of invalid JSON surfaces a ``ValueError`` with the source line."""
    path = tmp_path / "fpb.jsonl"
    path.write_text('{"id": "ok", "question": "q", "gold_answer": "neutral"}\n{not json\n', encoding="utf-8")
    ds = FPBDataset(data_path=path)
    with pytest.raises(ValueError) as excinfo:
        list(ds.load())
    assert ":2:" in str(excinfo.value)


def test_iter_jsonl_skips_blanks_and_comments(
    tmp_path: Path, fpb_records: list[dict[str, object]]
) -> None:
    """Blank lines and ``#``-prefixed comments are silently skipped."""
    path = tmp_path / "fpb.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# header comment\n")
        fh.write("\n")
        for rec in fpb_records:
            fh.write(json.dumps(rec) + "\n")
        fh.write("   \n")
    ds = FPBDataset(data_path=path)
    examples = list(ds.load())
    assert len(examples) == len(fpb_records)


def test_missing_data_error_includes_hint(tmp_path: Path) -> None:
    """``FileNotFoundError`` message includes the ``_MISSING_HINT`` text."""
    ds = FiQASADataset(data_path=tmp_path / "nope.jsonl")
    with pytest.raises(FileNotFoundError) as excinfo:
        list(ds.load())
    assert "data/README.md" in str(excinfo.value)


def test_id_and_question_coerced_to_string(tmp_path: Path) -> None:
    """Numeric ``id`` values in JSONL are coerced to ``str`` on load."""
    record = {
        "id": 42,
        "question": "Sentiment? positive / negative / neutral.",
        "gold_answer": "neutral",
        "aspect": "misc",
    }
    path = _write_jsonl(tmp_path / "fpb.jsonl", [record])
    ds = FPBDataset(data_path=path)
    [ex] = list(ds.load())
    assert ex.id == "42"
    assert isinstance(ex.id, str)


def test_hash_is_stable_across_runs(fpb_jsonl: Path) -> None:
    """``Dataset.hash()`` is deterministic for the same on-disk content."""
    ds_a = FPBDataset(data_path=fpb_jsonl)
    ds_b = FPBDataset(data_path=fpb_jsonl)
    assert ds_a.hash() == ds_b.hash()


def test_hash_changes_when_ids_change(
    tmp_path: Path, fpb_records: list[dict[str, object]]
) -> None:
    """Mutating an example ID changes the dataset hash."""
    path_a = _write_jsonl(tmp_path / "a.jsonl", fpb_records)
    fpb_records[0]["id"] = "fpb-001-mutated"
    path_b = _write_jsonl(tmp_path / "b.jsonl", fpb_records)
    assert FPBDataset(data_path=path_a).hash() != FPBDataset(data_path=path_b).hash()


def test_module_all_exports() -> None:
    """``__all__`` exposes both dataset classes in the documented order."""
    from lub.benchmarks import financial_sentiment

    assert financial_sentiment.__all__ == ["FPBDataset", "FiQASADataset"]
