# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Smoke tests for credit-scoring and financial-sentiment datasets.

These datasets ship with their JSONL payloads as part of the wheel; if
the payload is not yet materialized, the loader is expected to raise
FileNotFoundError with an actionable message. That is the scenario
these tests cover — we verify the class wiring, name/version, and the
error surface, without depending on the full data being present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.benchmarks import (
    AustralianCreditDataset,
    FiQASADataset,
    FPBDataset,
    GermanCreditDataset,
)


@pytest.mark.parametrize(
    "cls, expected_name",
    [
        (GermanCreditDataset, "german_credit"),
        (AustralianCreditDataset, "australian_credit"),
        (FPBDataset, "fpb"),
        (FiQASADataset, "fiqa_sa"),
    ],
)
def test_dataset_name(cls: type, expected_name: str) -> None:
    assert cls().name == expected_name


@pytest.mark.parametrize(
    "cls",
    [GermanCreditDataset, AustralianCreditDataset, FPBDataset, FiQASADataset],
)
def test_dataset_version_is_semver(cls: type) -> None:
    v = cls().version
    assert isinstance(v, str)
    parts = v.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


@pytest.mark.parametrize(
    "cls",
    [GermanCreditDataset, AustralianCreditDataset, FPBDataset, FiQASADataset],
)
def test_load_raises_when_data_file_missing(cls: type, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.jsonl"
    ds = cls(data_path=missing)
    with pytest.raises(FileNotFoundError):
        list(ds.load())


def test_loader_parses_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "tiny.jsonl"
    p.write_text(
        '{"id": "1", "question": "Q1", "gold_answer": "Approve", "label": 1}\n'
        '{"id": "2", "question": "Q2", "gold_answer": "Deny", "label": 0}\n',
        encoding="utf-8",
    )
    ds = GermanCreditDataset(data_path=p)
    examples = list(ds.load())
    assert len(examples) == 2
    assert examples[0].id == "1"
    assert examples[0].question == "Q1"
    assert examples[1].gold_answer == "Deny"
    assert examples[0].metadata["source"] == "german_credit"


def test_loader_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    p = tmp_path / "with_comments.jsonl"
    p.write_text(
        "# header comment\n"
        "\n"
        '{"id": "1", "question": "Q", "gold_answer": "positive"}\n'
        "# footer comment\n",
        encoding="utf-8",
    )
    ds = FPBDataset(data_path=p)
    assert len(list(ds.load())) == 1


def test_loader_rejects_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text("{not valid json\n", encoding="utf-8")
    ds = FiQASADataset(data_path=p)
    with pytest.raises(ValueError, match="invalid JSON"):
        list(ds.load())
