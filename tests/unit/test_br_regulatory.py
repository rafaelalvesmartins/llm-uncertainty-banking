# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.benchmarks.br_regulatory`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.br_regulatory import BrazilianRegulatoryDataset


@pytest.fixture
def sample_records() -> list[dict[str, str]]:
    """Two well-formed JSONL records matching the br_regulatory schema."""
    return [
        {
            "id": "brreg-001",
            "question": "What is the minimum CET1 ratio under Basel III?",
            "gold_answer": "4.5%",
            "source_url": "https://www.bis.org/bcbs/publ/d424.htm",
            "topic": "Basel III capital ratios",
        },
        {
            "id": "brreg-002",
            "question": "What is the minimum total capital ratio under Basel III?",
            "gold_answer": "8%",
            "source_url": "https://www.bis.org/bcbs/publ/d424.htm",
            "topic": "Basel III capital ratios",
        },
    ]


@pytest.fixture
def jsonl_file(tmp_path: Path, sample_records: list[dict[str, str]]) -> Path:
    """Write *sample_records* to a temp JSONL file and return the path."""
    path = tmp_path / "br_regulatory.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for rec in sample_records:
            fh.write(json.dumps(rec) + "\n")
    return path


class TestClassConfiguration:
    """The subclass declares its ClassVars correctly for the JsonlDataset base."""

    def test_registry_key_is_br_regulatory(self) -> None:
        assert BrazilianRegulatoryDataset.REGISTRY_KEY == "br_regulatory"

    def test_filename_is_br_regulatory_jsonl(self) -> None:
        assert BrazilianRegulatoryDataset._FILENAME == "br_regulatory.jsonl"

    def test_name_constant_is_br_regulatory(self) -> None:
        assert BrazilianRegulatoryDataset._NAME == "br_regulatory"

    def test_version_constant_is_set(self) -> None:
        assert BrazilianRegulatoryDataset._VERSION == "0.1.0"

    def test_metadata_keys_are_source_url_and_topic(self) -> None:
        assert BrazilianRegulatoryDataset._METADATA_KEYS == ("source_url", "topic")

    def test_missing_hint_points_to_reinstall_or_readme(self) -> None:
        hint = BrazilianRegulatoryDataset._MISSING_HINT
        assert "reinstall" in hint.lower() or "readme" in hint.lower()

    def test_auto_registers_in_dataset_registry(self) -> None:
        assert Dataset.get_dataset_cls("br_regulatory") is BrazilianRegulatoryDataset

    def test_module_exports_dataset_class(self) -> None:
        from lub.benchmarks import br_regulatory

        assert br_regulatory.__all__ == ["BrazilianRegulatoryDataset"]


class TestInstanceProperties:
    """Public properties expose the configured name/version."""

    def test_name_property_returns_class_name(self) -> None:
        ds = BrazilianRegulatoryDataset()
        assert ds.name == "br_regulatory"

    def test_version_property_returns_class_version(self) -> None:
        ds = BrazilianRegulatoryDataset()
        assert ds.version == "0.1.0"

    def test_default_data_path_points_into_benchmarks_data_dir(self) -> None:
        ds = BrazilianRegulatoryDataset()
        assert ds.data_path.name == "br_regulatory.jsonl"
        assert ds.data_path.parent.name == "data"

    def test_custom_data_path_is_respected(self, tmp_path: Path) -> None:
        custom = tmp_path / "elsewhere.jsonl"
        ds = BrazilianRegulatoryDataset(data_path=custom)
        assert ds.data_path == custom


class TestLoad:
    """``load()`` streams Example records that match the JSONL schema."""

    def test_load_yields_examples(self, jsonl_file: Path) -> None:
        ds = BrazilianRegulatoryDataset(data_path=jsonl_file)
        examples = list(ds.load())
        assert len(examples) == 2
        assert all(isinstance(e, Example) for e in examples)

    def test_load_preserves_record_fields(self, jsonl_file: Path) -> None:
        ds = BrazilianRegulatoryDataset(data_path=jsonl_file)
        first = next(iter(ds.load()))
        assert first.id == "brreg-001"
        assert "CET1" in first.question
        assert first.gold_answer == "4.5%"

    def test_load_populates_declared_metadata_keys(self, jsonl_file: Path) -> None:
        ds = BrazilianRegulatoryDataset(data_path=jsonl_file)
        first = next(iter(ds.load()))
        assert first.metadata["source_url"].startswith("https://www.bis.org")
        assert first.metadata["topic"] == "Basel III capital ratios"

    def test_load_tags_metadata_with_source_name(self, jsonl_file: Path) -> None:
        ds = BrazilianRegulatoryDataset(data_path=jsonl_file)
        first = next(iter(ds.load()))
        assert first.metadata["source"] == "br_regulatory"

    def test_load_raises_filenotfound_when_path_missing(self, tmp_path: Path) -> None:
        ds = BrazilianRegulatoryDataset(data_path=tmp_path / "missing.jsonl")
        with pytest.raises(FileNotFoundError) as exc_info:
            list(ds.load())
        assert "br_regulatory" in str(exc_info.value)

    def test_load_filenotfound_includes_missing_hint(self, tmp_path: Path) -> None:
        ds = BrazilianRegulatoryDataset(data_path=tmp_path / "missing.jsonl")
        with pytest.raises(FileNotFoundError) as exc_info:
            list(ds.load())
        msg = str(exc_info.value).lower()
        assert "reinstall" in msg or "readme" in msg

    def test_load_raises_valueerror_for_malformed_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.jsonl"
        bad.write_text("{not valid json\n", encoding="utf-8")
        ds = BrazilianRegulatoryDataset(data_path=bad)
        with pytest.raises(ValueError):
            list(ds.load())

    def test_load_skips_blank_and_comment_lines(
        self, tmp_path: Path, sample_records: list[dict[str, str]]
    ) -> None:
        path = tmp_path / "mixed.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("# leading comment\n")
            fh.write(json.dumps(sample_records[0]) + "\n")
            fh.write("\n")
            fh.write("# trailing comment\n")
            fh.write(json.dumps(sample_records[1]) + "\n")
        ds = BrazilianRegulatoryDataset(data_path=path)
        examples = list(ds.load())
        assert [e.id for e in examples] == ["brreg-001", "brreg-002"]


class TestBundledDataset:
    """Smoke tests against the JSONL file bundled with the package."""

    def test_bundled_file_loads_without_error(self) -> None:
        ds = BrazilianRegulatoryDataset()
        examples = list(ds.load())
        assert len(examples) > 0

    def test_bundled_ids_use_brreg_prefix(self) -> None:
        ds = BrazilianRegulatoryDataset()
        for ex in ds.load():
            assert ex.id.startswith("brreg-"), f"unexpected id: {ex.id}"

    def test_bundled_ids_are_unique(self) -> None:
        ds = BrazilianRegulatoryDataset()
        ids = [ex.id for ex in ds.load()]
        assert len(ids) == len(set(ids))

    def test_bundled_validate_returns_no_warnings(self) -> None:
        ds = BrazilianRegulatoryDataset()
        assert ds.validate(limit=5) == []
