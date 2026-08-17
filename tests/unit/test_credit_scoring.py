# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.benchmarks.credit_scoring`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.credit_scoring import (
    AustralianCreditDataset,
    GermanCreditDataset,
)

_CLASSES = [
    (GermanCreditDataset, "german_credit", "german_credit.jsonl"),
    (AustralianCreditDataset, "australian_credit", "australian_credit.jsonl"),
]


@pytest.fixture
def german_records() -> list[dict[str, object]]:
    """Two well-formed JSONL records matching the german_credit schema."""
    return [
        {
            "id": "gc-001",
            "question": "Applicant earns 3500 EUR/mo, requests 5000 EUR. Approve?",
            "gold_answer": "Approve",
            "label": 1,
        },
        {
            "id": "gc-002",
            "question": "Applicant has 4 outstanding loans, requests 10000 EUR. Approve?",
            "gold_answer": "Deny",
            "label": 0,
        },
    ]


@pytest.fixture
def australian_records() -> list[dict[str, object]]:
    """Two well-formed JSONL records matching the australian_credit schema."""
    return [
        {
            "id": "ac-001",
            "question": "Applicant A14 features summarized; approve?",
            "gold_answer": "Approve",
            "label": 1,
        },
        {
            "id": "ac-002",
            "question": "Applicant A14 features summarized; approve?",
            "gold_answer": "Deny",
            "label": 0,
        },
    ]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


@pytest.fixture
def german_jsonl(tmp_path: Path, german_records: list[dict[str, object]]) -> Path:
    return _write_jsonl(tmp_path / "german_credit.jsonl", german_records)


@pytest.fixture
def australian_jsonl(
    tmp_path: Path, australian_records: list[dict[str, object]]
) -> Path:
    return _write_jsonl(tmp_path / "australian_credit.jsonl", australian_records)


@pytest.mark.parametrize("cls, expected_name, _filename", _CLASSES)
def test_class_attributes_are_wired(
    cls: type, expected_name: str, _filename: str
) -> None:
    """Each dataset exposes the documented class-level attributes."""
    assert cls.REGISTRY_KEY == expected_name
    assert cls._NAME == expected_name
    assert cls._FILENAME == _filename
    assert cls._METADATA_KEYS == ("label",)


@pytest.mark.parametrize("cls, expected_name, _filename", _CLASSES)
def test_instance_is_a_dataset(cls: type, expected_name: str, _filename: str) -> None:
    """Instances satisfy the abstract :class:`Dataset` contract."""
    ds = cls()
    assert isinstance(ds, Dataset)
    assert ds.name == expected_name
    parts = ds.version.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


@pytest.mark.parametrize("cls, expected_name, _filename", _CLASSES)
def test_auto_registration(cls: type, expected_name: str, _filename: str) -> None:
    """Importing the module registers each dataset under its key."""
    assert Dataset.get_dataset_cls(expected_name) is cls


@pytest.mark.parametrize("cls, expected_name, _filename", _CLASSES)
def test_default_data_path_points_inside_package(
    cls: type, expected_name: str, _filename: str
) -> None:
    """Default ``data_path`` resolves to the packaged ``benchmarks/data`` dir."""
    ds = cls()
    assert ds.data_path.name == _filename
    assert ds.data_path.parent.name == "data"


@pytest.mark.parametrize("cls, expected_name, _filename", _CLASSES)
def test_load_raises_when_data_file_missing(
    cls: type, expected_name: str, _filename: str, tmp_path: Path
) -> None:
    """Missing JSONL file raises ``FileNotFoundError`` with the name in it."""
    missing = tmp_path / "does_not_exist.jsonl"
    ds = cls(data_path=missing)
    with pytest.raises(FileNotFoundError) as excinfo:
        list(ds.load())
    assert expected_name in str(excinfo.value)


def test_german_credit_loads_examples(german_jsonl: Path) -> None:
    """GermanCreditDataset parses JSONL records into Example tuples."""
    ds = GermanCreditDataset(data_path=german_jsonl)
    examples = list(ds.load())
    assert len(examples) == 2
    assert all(isinstance(ex, Example) for ex in examples)
    assert examples[0].id == "gc-001"
    assert examples[0].question.startswith("Applicant earns")
    assert examples[0].gold_answer == "Approve"
    assert examples[1].gold_answer == "Deny"


def test_german_credit_metadata_carries_label_and_source(german_jsonl: Path) -> None:
    """``label`` is preserved verbatim and ``source`` is set to the dataset name."""
    ds = GermanCreditDataset(data_path=german_jsonl)
    examples = list(ds.load())
    assert examples[0].metadata["label"] == 1
    assert examples[1].metadata["label"] == 0
    assert all(ex.metadata["source"] == "german_credit" for ex in examples)


def test_australian_credit_loads_examples(australian_jsonl: Path) -> None:
    """AustralianCreditDataset parses JSONL records into Example tuples."""
    ds = AustralianCreditDataset(data_path=australian_jsonl)
    examples = list(ds.load())
    assert len(examples) == 2
    assert examples[0].id == "ac-001"
    assert examples[0].gold_answer == "Approve"
    assert examples[1].metadata["source"] == "australian_credit"
    assert examples[1].metadata["label"] == 0


def test_load_is_lazy_iterator(german_jsonl: Path) -> None:
    """``load`` returns an iterator, not a pre-materialized list."""
    ds = GermanCreditDataset(data_path=german_jsonl)
    it = ds.load()
    assert iter(it) is it
    first = next(it)
    assert first.id == "gc-001"


def test_validate_passes_on_well_formed_records(german_jsonl: Path) -> None:
    """``validate`` returns an empty list for clean JSONL."""
    ds = GermanCreditDataset(data_path=german_jsonl)
    assert ds.validate() == []


def test_validate_flags_blank_question(
    tmp_path: Path, german_records: list[dict[str, object]]
) -> None:
    """``validate`` flags rows with a blank ``question`` field."""
    german_records[0]["question"] = "   "
    path = _write_jsonl(tmp_path / "bad.jsonl", german_records)
    ds = GermanCreditDataset(data_path=path)
    warnings = ds.validate()
    assert any("question is blank" in w for w in warnings)


def test_missing_data_error_includes_hint(tmp_path: Path) -> None:
    """``FileNotFoundError`` message includes the ``_MISSING_HINT`` text."""
    ds = AustralianCreditDataset(data_path=tmp_path / "nope.jsonl")
    with pytest.raises(FileNotFoundError) as excinfo:
        list(ds.load())
    assert "data/README.md" in str(excinfo.value)


def test_module_all_exports() -> None:
    """``__all__`` exposes both dataset classes in alphabetical order."""
    from lub.benchmarks import credit_scoring

    assert credit_scoring.__all__ == ["AustralianCreditDataset", "GermanCreditDataset"]
