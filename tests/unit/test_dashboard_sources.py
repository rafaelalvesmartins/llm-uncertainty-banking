# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Tests for lub.reports.dashboard_sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lub.reports.dashboard_sources import (
    DirEvidenceSource,
    InMemoryEvidenceSource,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def benchmark_payload() -> dict[str, Any]:
    return {
        "estimator": "logits_softmax",
        "dataset": "banking77",
        "n": 100,
        "accuracy": 0.85,
        "ece": 0.07,
    }


@pytest.fixture
def oscal_payload() -> dict[str, Any]:
    return {
        "assessment-results": {
            "uuid": "abc-123",
            "metadata": {"title": "Test Assessment"},
        }
    }


@pytest.fixture
def unknown_payload() -> dict[str, Any]:
    return {"foo": "bar", "baz": 42}


@pytest.fixture
def results_dir(
    tmp_path: Path,
    benchmark_payload: dict[str, Any],
    oscal_payload: dict[str, Any],
    unknown_payload: dict[str, Any],
) -> Path:
    (tmp_path / "bench.json").write_text(
        json.dumps(benchmark_payload), encoding="utf-8"
    )
    (tmp_path / "oscal.json").write_text(
        json.dumps(oscal_payload), encoding="utf-8"
    )
    (tmp_path / "other.json").write_text(
        json.dumps(unknown_payload), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# DirEvidenceSource
# ---------------------------------------------------------------------------


class TestDirEvidenceSource:
    def test_iter_benchmark_results_returns_benchmark_payloads(
        self, results_dir: Path, benchmark_payload: dict[str, Any]
    ) -> None:
        src = DirEvidenceSource(results_dir)
        results = list(src.iter_benchmark_results())
        assert len(results) == 1
        assert results[0] == benchmark_payload

    def test_iter_oscal_assessments_returns_oscal_payloads(
        self, results_dir: Path, oscal_payload: dict[str, Any]
    ) -> None:
        src = DirEvidenceSource(results_dir)
        results = list(src.iter_oscal_assessments())
        assert len(results) == 1
        assert results[0] == oscal_payload

    def test_iter_artefacts_classifies_all_three_kinds(
        self, results_dir: Path
    ) -> None:
        src = DirEvidenceSource(results_dir)
        artefacts = list(src.iter_artefacts())
        kinds = {a["kind"] for a in artefacts}
        assert kinds == {"benchmark", "oscal", "other"}
        assert len(artefacts) == 3

    def test_iter_artefacts_each_record_has_name_and_kind(
        self, results_dir: Path
    ) -> None:
        src = DirEvidenceSource(results_dir)
        for artefact in src.iter_artefacts():
            assert "name" in artefact
            assert "kind" in artefact
            assert artefact["name"].endswith(".json")

    def test_missing_directory_emits_warning(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        src = DirEvidenceSource(missing)
        warnings = src.warnings()
        assert len(warnings) == 1
        assert "does not exist" in warnings[0]
        assert list(src.iter_benchmark_results()) == []
        assert list(src.iter_oscal_assessments()) == []

    def test_results_dir_is_file_not_directory_warns(
        self, tmp_path: Path
    ) -> None:
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello", encoding="utf-8")
        src = DirEvidenceSource(file_path)
        warnings = src.warnings()
        assert len(warnings) == 1
        assert "does not exist" in warnings[0]

    def test_malformed_json_is_skipped_with_warning(
        self, tmp_path: Path, benchmark_payload: dict[str, Any]
    ) -> None:
        (tmp_path / "good.json").write_text(
            json.dumps(benchmark_payload), encoding="utf-8"
        )
        (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")
        src = DirEvidenceSource(tmp_path)
        results = list(src.iter_benchmark_results())
        warnings = src.warnings()
        assert len(results) == 1
        assert any("bad.json" in w for w in warnings)

    def test_scan_is_cached_across_calls(
        self, results_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = DirEvidenceSource(results_dir)
        list(src.iter_benchmark_results())
        call_count = {"n": 0}
        original_glob = Path.glob

        def counting_glob(self: Path, pattern: str) -> Any:
            call_count["n"] += 1
            return original_glob(self, pattern)

        monkeypatch.setattr(Path, "glob", counting_glob)
        list(src.iter_benchmark_results())
        list(src.iter_oscal_assessments())
        list(src.iter_artefacts())
        assert call_count["n"] == 0

    def test_string_path_accepted(
        self, results_dir: Path, benchmark_payload: dict[str, Any]
    ) -> None:
        src = DirEvidenceSource(str(results_dir))
        results = list(src.iter_benchmark_results())
        assert results == [benchmark_payload]

    def test_empty_directory_returns_empty_lists(self, tmp_path: Path) -> None:
        src = DirEvidenceSource(tmp_path)
        assert list(src.iter_benchmark_results()) == []
        assert list(src.iter_oscal_assessments()) == []
        assert list(src.iter_artefacts()) == []
        assert src.warnings() == []

    def test_regime_coverage_returns_list(self, results_dir: Path) -> None:
        src = DirEvidenceSource(results_dir)
        rows = src.regime_coverage()
        assert isinstance(rows, list)
        for row in rows:
            assert "key" in row
            assert "name" in row
            assert "n_controls" in row

    def test_iter_methods_return_independent_copies(
        self, results_dir: Path
    ) -> None:
        src = DirEvidenceSource(results_dir)
        first = list(src.iter_benchmark_results())
        second = list(src.iter_benchmark_results())
        assert first == second
        assert first is not second


# ---------------------------------------------------------------------------
# InMemoryEvidenceSource
# ---------------------------------------------------------------------------


class TestInMemoryEvidenceSource:
    def test_defaults_are_empty(self) -> None:
        src = InMemoryEvidenceSource()
        assert list(src.iter_benchmark_results()) == []
        assert list(src.iter_oscal_assessments()) == []
        assert list(src.iter_artefacts()) == []
        assert src.regime_coverage() == []
        assert src.warnings() == []

    def test_iter_benchmark_results_returns_payloads(
        self, benchmark_payload: dict[str, Any]
    ) -> None:
        src = InMemoryEvidenceSource(benchmark_results=[benchmark_payload])
        assert list(src.iter_benchmark_results()) == [benchmark_payload]

    def test_iter_oscal_assessments_returns_payloads(
        self, oscal_payload: dict[str, Any]
    ) -> None:
        src = InMemoryEvidenceSource(oscal_assessments=[oscal_payload])
        assert list(src.iter_oscal_assessments()) == [oscal_payload]

    def test_iter_artefacts_returns_records(self) -> None:
        artefacts = [{"name": "a.json", "kind": "benchmark"}]
        src = InMemoryEvidenceSource(artefacts=artefacts)
        assert list(src.iter_artefacts()) == artefacts

    def test_regime_coverage_returns_rows(self) -> None:
        regimes = [{"key": "nist", "name": "NIST", "n_controls": 10}]
        src = InMemoryEvidenceSource(regimes=regimes)
        assert src.regime_coverage() == regimes

    def test_warnings_returns_list(self) -> None:
        warnings = ["something off"]
        src = InMemoryEvidenceSource(warnings_list=warnings)
        assert src.warnings() == warnings

    def test_returned_lists_are_copies(
        self, benchmark_payload: dict[str, Any]
    ) -> None:
        original = [benchmark_payload]
        src = InMemoryEvidenceSource(benchmark_results=original)
        returned = list(src.iter_benchmark_results())
        returned.append({"foo": "bar"})
        assert list(src.iter_benchmark_results()) == [benchmark_payload]

    def test_constructor_isolates_from_caller_mutation(
        self, benchmark_payload: dict[str, Any]
    ) -> None:
        original = [benchmark_payload]
        src = InMemoryEvidenceSource(benchmark_results=original)
        original.append({"estimator": "new"})
        assert list(src.iter_benchmark_results()) == [benchmark_payload]

    def test_all_kwargs_populated_together(
        self,
        benchmark_payload: dict[str, Any],
        oscal_payload: dict[str, Any],
    ) -> None:
        src = InMemoryEvidenceSource(
            benchmark_results=[benchmark_payload],
            oscal_assessments=[oscal_payload],
            artefacts=[{"name": "x.json", "kind": "other"}],
            regimes=[{"key": "iso", "name": "ISO", "n_controls": 5}],
            warnings_list=["w1"],
        )
        assert len(list(src.iter_benchmark_results())) == 1
        assert len(list(src.iter_oscal_assessments())) == 1
        assert len(list(src.iter_artefacts())) == 1
        assert len(src.regime_coverage()) == 1
        assert len(src.warnings()) == 1
