# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.benchmarks.finqa`.

The HuggingFace ``datasets`` library is patched out so the tests run
without network access. Coverage targets: the numeric filter, the
gold-answer fallback chain, ID generation, metadata propagation,
the empty-question skip, and registry registration.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.finqa import FinQADataset, _is_numeric

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_fake_datasets(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]
) -> None:
    """Install a fake ``datasets`` module that returns *rows* from load_dataset."""

    def fake_load_dataset(
        path: str, split: str = "test", revision: str | None = None
    ) -> list[dict[str, Any]]:
        return rows

    fake_mod = ModuleType("datasets")
    fake_mod.load_dataset = fake_load_dataset  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", fake_mod)


# ---------------------------------------------------------------------------
# _is_numeric
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "0",
        "1",
        "-1",
        "1.5",
        "-3.14",
        "1,200",
        "1,000,000",
        "$5",
        "$1,234.56",
        "12%",
        "0.5%",
        "(3.5)",
        "(100)",
        "  42  ",
        "1e3",
    ],
)
def test_is_numeric_accepts_financial_formats(text: str) -> None:
    assert _is_numeric(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "increased",
        "approximately 5",
        "n/a",
        "NA",
        "yes",
        "no",
        "$",
        "%",
        "()",
        "--",
        "1.2.3",
    ],
)
def test_is_numeric_rejects_non_numeric(text: str) -> None:
    assert _is_numeric(text) is False


def test_is_numeric_strips_whitespace_before_parsing() -> None:
    assert _is_numeric("\t 7.7 \n") is True


# ---------------------------------------------------------------------------
# Properties / construction
# ---------------------------------------------------------------------------


def test_default_constructor_uses_test_split_and_default_hf_path() -> None:
    ds = FinQADataset()
    assert ds.split == "test"
    assert ds.hf_path == "dreamerdeo/finqa"


def test_constructor_overrides_propagate() -> None:
    ds = FinQADataset(split="train", hf_path="custom/finqa")
    assert ds.split == "train"
    assert ds.hf_path == "custom/finqa"


def test_name_property_returns_registry_key() -> None:
    assert FinQADataset().name == "finqa"


def test_version_includes_hf_path_and_split() -> None:
    ds = FinQADataset(split="validation", hf_path="custom/path")
    assert ds.version == "custom/path:validation"


def test_default_version_uses_default_hf_path_and_test_split() -> None:
    assert FinQADataset().version == "dreamerdeo/finqa:test"


# ---------------------------------------------------------------------------
# Registry registration
# ---------------------------------------------------------------------------


def test_subclass_is_registered_under_finqa_key() -> None:
    assert "finqa" in Dataset._registry
    assert Dataset._registry["finqa"] is FinQADataset


def test_registry_lookup_returns_finqa_class() -> None:
    assert Dataset.get_dataset_cls("finqa") is FinQADataset


def test_list_datasets_includes_finqa() -> None:
    assert "finqa" in Dataset.list_datasets()


# ---------------------------------------------------------------------------
# load() — happy path & filtering
# ---------------------------------------------------------------------------


def test_load_yields_numeric_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"id": "ex-1", "question": "What was revenue?", "answer": "100"},
            {"id": "ex-2", "question": "What was margin?", "answer": "12.5%"},
        ],
    )
    ds = FinQADataset()
    examples = list(ds.load())
    assert len(examples) == 2
    assert all(isinstance(ex, Example) for ex in examples)
    assert examples[0].id == "ex-1"
    assert examples[0].question == "What was revenue?"
    assert examples[0].gold_answer == "100"
    assert examples[1].gold_answer == "12.5%"


def test_load_filters_out_non_numeric_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"id": "ok", "question": "Q numeric", "answer": "10"},
            {"id": "bad", "question": "Q text", "answer": "increased significantly"},
            {"id": "alsoOk", "question": "Q dollars", "answer": "$1,200"},
        ],
    )
    ds = FinQADataset()
    examples = list(ds.load())
    ids = [ex.id for ex in examples]
    assert ids == ["ok", "alsoOk"]


def test_load_skips_examples_with_blank_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"id": "ex-1", "question": "   ", "answer": "5"},
            {"id": "ex-2", "question": "", "answer": "6"},
            {"id": "ex-3", "question": "good", "answer": "7"},
        ],
    )
    ds = FinQADataset()
    examples = list(ds.load())
    assert [ex.id for ex in examples] == ["ex-3"]


def test_load_strips_whitespace_in_question_and_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "ex-1", "question": "  what?  ", "answer": "  3.14  "}],
    )
    ds = FinQADataset()
    ex = next(iter(ds.load()))
    assert ex.question == "what?"
    assert ex.gold_answer == "3.14"


# ---------------------------------------------------------------------------
# load() — gold-answer fallback chain
# ---------------------------------------------------------------------------


def test_load_uses_answer_field_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {
                "id": "ex-1",
                "question": "q",
                "answer": "1",
                "final_result": "2",
                "exe_ans": "3",
            }
        ],
    )
    ex = next(iter(FinQADataset().load()))
    assert ex.gold_answer == "1"


def test_load_falls_back_to_final_result_when_answer_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {
                "id": "ex-1",
                "question": "q",
                "final_result": "2",
                "exe_ans": "3",
            }
        ],
    )
    ex = next(iter(FinQADataset().load()))
    assert ex.gold_answer == "2"


def test_load_falls_back_to_exe_ans_when_others_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "ex-1", "question": "q", "exe_ans": "3"}],
    )
    ex = next(iter(FinQADataset().load()))
    assert ex.gold_answer == "3"


def test_load_skips_when_no_gold_answer_fields_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "ex-1", "question": "q"}],
    )
    assert list(FinQADataset().load()) == []


def test_load_falls_back_when_answer_is_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty ``answer`` is falsy under ``or`` and should fall through."""
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {
                "id": "ex-1",
                "question": "q",
                "answer": "",
                "final_result": "42",
            }
        ],
    )
    ex = next(iter(FinQADataset().load()))
    assert ex.gold_answer == "42"


# ---------------------------------------------------------------------------
# load() — ID generation
# ---------------------------------------------------------------------------


def test_load_uses_row_id_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "explicit-id", "question": "q", "answer": "1"}],
    )
    ex = next(iter(FinQADataset().load()))
    assert ex.id == "explicit-id"


def test_load_synthesizes_id_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"question": "q1", "answer": "1"},
            {"question": "q2", "answer": "2"},
        ],
    )
    examples = list(FinQADataset(split="test").load())
    assert [ex.id for ex in examples] == [
        "finqa-test-000000",
        "finqa-test-000001",
    ]


def test_load_synthesized_id_uses_split_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"question": "q", "answer": "1"}],
    )
    ex = next(iter(FinQADataset(split="train").load()))
    assert ex.id == "finqa-train-000000"


def test_load_synthesized_id_zero_pads_to_six_digits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"question": f"q{i}", "answer": str(i)} for i in range(3)],
    )
    examples = list(FinQADataset(split="test").load())
    for i, ex in enumerate(examples):
        assert ex.id.endswith(f"{i:06d}")


def test_load_row_indices_are_not_reset_by_skipped_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enumerate index advances through skipped rows, so synthesized IDs
    reflect the original row position rather than the kept-example position."""
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"question": "skip-text", "answer": "increased"},
            {"question": "keep", "answer": "1"},
        ],
    )
    examples = list(FinQADataset(split="test").load())
    assert len(examples) == 1
    assert examples[0].id == "finqa-test-000001"


# ---------------------------------------------------------------------------
# load() — metadata
# ---------------------------------------------------------------------------


def test_load_attaches_split_and_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "ex-1", "question": "q", "answer": "1"}],
    )
    ds = FinQADataset(split="train", hf_path="custom/path")
    ex = next(iter(ds.load()))
    assert ex.metadata == {"split": "train", "source": "custom/path"}


def test_load_metadata_uses_default_hf_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "ex-1", "question": "q", "answer": "1"}],
    )
    ex = next(iter(FinQADataset().load()))
    assert ex.metadata["source"] == "dreamerdeo/finqa"


# ---------------------------------------------------------------------------
# load() — return type & error surface
# ---------------------------------------------------------------------------


def test_load_returns_iterator_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[{"id": "ex-1", "question": "q", "answer": "1"}],
    )
    result = FinQADataset().load()
    assert isinstance(result, Iterator)
    assert not isinstance(result, list)


def test_load_raises_when_datasets_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force the ``datasets`` import inside ``load()`` to fail and confirm
    the error propagates rather than being silently swallowed."""
    monkeypatch.setitem(sys.modules, "datasets", None)
    with pytest.raises((ImportError, TypeError)):
        list(FinQADataset().load())


def test_load_propagates_load_dataset_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(path: str, split: str = "test", revision: str | None = None) -> Any:
        raise RuntimeError("HF backend unavailable")

    fake_mod = ModuleType("datasets")
    fake_mod.load_dataset = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", fake_mod)

    with pytest.raises(RuntimeError, match="HF backend unavailable"):
        list(FinQADataset().load())


def test_load_passes_configured_split_to_load_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_load_dataset(
        path: str, split: str = "test", revision: str | None = None
    ) -> list[dict[str, Any]]:
        captured["path"] = path
        captured["split"] = split
        return [{"question": "q", "answer": "1"}]

    fake_mod = ModuleType("datasets")
    fake_mod.load_dataset = fake_load_dataset  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", fake_mod)

    list(FinQADataset(split="validation", hf_path="x/y").load())
    assert captured == {"path": "x/y", "split": "validation"}


# ---------------------------------------------------------------------------
# validate() — inherited base behavior
# ---------------------------------------------------------------------------


def test_validate_returns_empty_for_clean_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_datasets(
        monkeypatch,
        rows=[
            {"id": "ex-1", "question": "Q1", "answer": "1"},
            {"id": "ex-2", "question": "Q2", "answer": "2"},
        ],
    )
    warnings = FinQADataset().validate(limit=5)
    assert warnings == []


# ---------------------------------------------------------------------------
# __all__ surface
# ---------------------------------------------------------------------------


def test_module_exports_only_finqa_dataset() -> None:
    import lub.benchmarks.finqa as mod

    assert mod.__all__ == ["FinQADataset"]
