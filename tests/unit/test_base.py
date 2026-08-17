# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.benchmarks.base`."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lub.benchmarks import base as base_mod
from lub.benchmarks.base import Dataset, Example, iter_jsonl

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def jsonl_file(tmp_path: Path) -> Path:
    """Write a JSONL file with blank lines, comments, and valid records."""
    p = tmp_path / "data.jsonl"
    p.write_text(
        "\n"
        "# header comment\n"
        '{"a": 1}\n'
        "   \n"
        '{"b": 2}\n',
        encoding="utf-8",
    )
    return p


@pytest.fixture
def restore_registry() -> Iterator[None]:
    """Snapshot the Dataset registry around a test that mutates it."""
    original = dict(Dataset._registry)
    yield
    Dataset._registry.clear()
    Dataset._registry.update(original)


# --------------------------------------------------------------------------- #
# Helper concrete subclasses
# --------------------------------------------------------------------------- #


class _DummyDataset(Dataset):
    """Two clean examples — used for hash and validate happy-path tests."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def version(self) -> str:
        return "v0"

    def load(self) -> Iterator[Example]:
        yield Example(id="1", question="q1", gold_answer="a1", metadata={})
        yield Example(id="2", question="q2", gold_answer="a2", metadata={"k": "v"})


class _BlankDataset(Dataset):
    """Examples with blank fields — exercises validate() warnings."""

    @property
    def name(self) -> str:
        return "blank"

    @property
    def version(self) -> str:
        return "v0"

    def load(self) -> Iterator[Example]:
        yield Example(id="b1", question="   ", gold_answer="a", metadata={})
        yield Example(id="b2", question="q", gold_answer="", metadata={})


# --------------------------------------------------------------------------- #
# iter_jsonl
# --------------------------------------------------------------------------- #


def test_iter_jsonl_yields_records_with_line_numbers(jsonl_file: Path) -> None:
    assert list(iter_jsonl(jsonl_file)) == [(3, {"a": 1}), (5, {"b": 2})]


def test_iter_jsonl_skips_only_blanks_and_comments(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("# c1\n\n   \n# c2\n", encoding="utf-8")
    assert list(iter_jsonl(p)) == []


def test_iter_jsonl_raises_value_error_with_source_line(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text("\n{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:2:"):
        list(iter_jsonl(p))


# --------------------------------------------------------------------------- #
# Example
# --------------------------------------------------------------------------- #


def test_example_namedtuple_fields_and_positional_order() -> None:
    ex = Example(id="x", question="q?", gold_answer="42", metadata={"k": 1})
    assert (ex.id, ex.question, ex.gold_answer, ex.metadata) == (
        "x",
        "q?",
        "42",
        {"k": 1},
    )
    assert tuple(ex) == ("x", "q?", "42", {"k": 1})


# --------------------------------------------------------------------------- #
# Dataset subclass auto-registration
# --------------------------------------------------------------------------- #


def test_subclass_with_registry_key_is_registered(restore_registry: None) -> None:
    class FooDataset(Dataset):
        REGISTRY_KEY = "foo_test_key"

        @property
        def name(self) -> str:
            return "foo"

        @property
        def version(self) -> str:
            return "v0"

        def load(self) -> Iterator[Example]:
            return iter(())

    assert Dataset._registry["foo_test_key"] is FooDataset


def test_subclass_without_registry_key_is_not_registered(
    restore_registry: None,
) -> None:
    before = dict(Dataset._registry)

    class _Anon(Dataset):  # noqa: D401 — test helper
        @property
        def name(self) -> str:
            return "anon"

        @property
        def version(self) -> str:
            return "v0"

        def load(self) -> Iterator[Example]:
            return iter(())

    assert Dataset._registry == before


def test_inherited_registry_key_not_re_registered(restore_registry: None) -> None:
    """A subclass that does not redeclare REGISTRY_KEY must not steal the slot."""

    class Parent(Dataset):
        REGISTRY_KEY = "parent_key"

        @property
        def name(self) -> str:
            return "p"

        @property
        def version(self) -> str:
            return "v"

        def load(self) -> Iterator[Example]:
            return iter(())

    class Child(Parent):
        pass

    assert Dataset._registry["parent_key"] is Parent


# --------------------------------------------------------------------------- #
# Dataset.validate
# --------------------------------------------------------------------------- #


def test_validate_returns_empty_for_clean_data() -> None:
    assert _DummyDataset().validate() == []


def test_validate_flags_blank_question_and_blank_answer() -> None:
    warnings = _BlankDataset().validate()
    assert any("'b1'" in w and "question" in w for w in warnings)
    assert any("'b2'" in w and "gold_answer" in w for w in warnings)


def test_validate_respects_explicit_limit() -> None:
    warnings = _BlankDataset().validate(limit=1)
    assert any("'b1'" in w for w in warnings)
    assert not any("'b2'" in w for w in warnings)


def test_validate_with_none_limit_walks_all_examples() -> None:
    warnings = _BlankDataset().validate(limit=None)
    assert any("'b1'" in w for w in warnings)
    assert any("'b2'" in w for w in warnings)


# --------------------------------------------------------------------------- #
# Dataset.get_dataset_cls
# --------------------------------------------------------------------------- #


def test_get_dataset_cls_returns_already_registered(
    restore_registry: None,
) -> None:
    class BarDataset(Dataset):
        REGISTRY_KEY = "bar_test_key"

        @property
        def name(self) -> str:
            return "bar"

        @property
        def version(self) -> str:
            return "v0"

        def load(self) -> Iterator[Example]:
            return iter(())

    assert Dataset.get_dataset_cls("bar_test_key") is BarDataset


def test_get_dataset_cls_raises_for_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        Dataset.get_dataset_cls("this_key_does_not_exist_xyz")


def test_get_dataset_cls_lazily_imports_module(
    restore_registry: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LazyDataset(Dataset):
        REGISTRY_KEY = "lazy_test_key"

        @property
        def name(self) -> str:
            return "lazy"

        @property
        def version(self) -> str:
            return "v0"

        def load(self) -> Iterator[Example]:
            return iter(())

    # Simulate "not yet imported": drop from live registry.
    Dataset._registry.pop("lazy_test_key", None)

    monkeypatch.setattr(
        base_mod, "_LAZY_REGISTRY", {"lazy_test_key": "fake.module.path"}
    )

    called_with: list[str] = []

    def fake_import(name: str) -> Any:
        called_with.append(name)
        # Simulate the module registering itself on import.
        Dataset._registry["lazy_test_key"] = LazyDataset
        return None

    import importlib

    monkeypatch.setattr(importlib, "import_module", fake_import)

    resolved = Dataset.get_dataset_cls("lazy_test_key")
    assert resolved is LazyDataset
    assert called_with == ["fake.module.path"]


def test_get_dataset_cls_error_message_lists_known_keys() -> None:
    with pytest.raises(ValueError) as exc_info:
        Dataset.get_dataset_cls("nonexistent_key_qwerty")
    msg = str(exc_info.value)
    # Any well-known lazy key should appear in the help message.
    assert "finqa" in msg


# --------------------------------------------------------------------------- #
# Dataset.list_datasets
# --------------------------------------------------------------------------- #


def test_list_datasets_is_sorted_and_includes_lazy_keys() -> None:
    keys = Dataset.list_datasets()
    assert keys == sorted(keys)
    assert "finqa" in keys
    assert "fpb" in keys


def test_list_datasets_includes_live_registrations(
    restore_registry: None,
) -> None:
    class LiveDataset(Dataset):
        REGISTRY_KEY = "live_only_test_key"

        @property
        def name(self) -> str:
            return "live"

        @property
        def version(self) -> str:
            return "v0"

        def load(self) -> Iterator[Example]:
            return iter(())

    assert "live_only_test_key" in Dataset.list_datasets()


# --------------------------------------------------------------------------- #
# Dataset.hash
# --------------------------------------------------------------------------- #


def test_hash_is_sha256_of_concatenated_ids_with_newlines() -> None:
    expected = hashlib.sha256(b"1\n2\n").hexdigest()
    assert _DummyDataset().hash() == expected


def test_hash_is_deterministic_across_calls() -> None:
    ds = _DummyDataset()
    assert ds.hash() == ds.hash()


def test_hash_differs_when_ids_differ() -> None:
    class OtherDataset(Dataset):
        @property
        def name(self) -> str:
            return "other"

        @property
        def version(self) -> str:
            return "v0"

        def load(self) -> Iterator[Example]:
            yield Example(id="9", question="q", gold_answer="a", metadata={})

    assert _DummyDataset().hash() != OtherDataset().hash()
