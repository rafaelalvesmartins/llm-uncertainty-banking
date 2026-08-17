# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from lub.benchmarks.base import Example
from lub.benchmarks.br_regulatory import BrazilianRegulatoryDataset


def test_br_regulatory_loads_nonempty() -> None:
    ds = BrazilianRegulatoryDataset()
    examples = list(ds.load())
    assert len(examples) >= 20
    assert all(isinstance(e, Example) for e in examples)


def test_br_regulatory_example_shape() -> None:
    ds = BrazilianRegulatoryDataset()
    first = next(iter(ds.load()))
    assert first.id.startswith("brreg-")
    assert first.question
    assert first.gold_answer
    assert "source_url" in first.metadata
    assert "topic" in first.metadata


def test_br_regulatory_ids_are_unique() -> None:
    ds = BrazilianRegulatoryDataset()
    ids = [e.id for e in ds.load()]
    assert len(ids) == len(set(ids))


def test_br_regulatory_name_and_version() -> None:
    ds = BrazilianRegulatoryDataset()
    assert ds.name == "br_regulatory"
    assert ds.version == "0.1.0"


def test_br_regulatory_hash_is_stable() -> None:
    ds = BrazilianRegulatoryDataset()
    h1 = ds.hash()
    h2 = ds.hash()
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_br_regulatory_missing_file_raises(tmp_path: Path) -> None:
    ds = BrazilianRegulatoryDataset(data_path=tmp_path / "nope.jsonl")
    with pytest.raises(FileNotFoundError):
        list(ds.load())


def test_br_regulatory_bad_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json at all\n", encoding="utf-8")
    ds = BrazilianRegulatoryDataset(data_path=bad)
    with pytest.raises(ValueError):
        list(ds.load())
