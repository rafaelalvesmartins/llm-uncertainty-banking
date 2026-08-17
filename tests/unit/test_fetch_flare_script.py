# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Static consistency tests for scripts/fetch_flare_datasets.py.

Does not run the script end-to-end — that requires a HuggingFace
download and is not hermetic. Instead, verifies that:

1. The script parses under Python without errors.
2. The ``_TASKS`` registry covers every stub loader that expects a
   packaged JSONL file under ``src/lub/benchmarks/data/``.
3. The ``_row_to_record`` mapper produces LUB-shaped output for a
   synthetic HF-style row.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "fetch_flare_datasets.py"


def _load_script_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("fetch_flare_script", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_flare_script"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module():  # type: ignore[no-untyped-def]
    return _load_script_module()


def test_script_parses(script_module) -> None:  # type: ignore[no-untyped-def]
    assert hasattr(script_module, "_TASKS")
    assert hasattr(script_module, "main")


def test_tasks_cover_stub_loaders(script_module) -> None:  # type: ignore[no-untyped-def]
    # Every loader that expects a packaged JSONL must be fetchable.
    expected = {"fpb", "fiqa_sa", "german_credit", "australian_credit"}
    script_names = {task.lub_name for task in script_module._TASKS}
    assert expected <= script_names


def test_out_filenames_match_loader_expectations(script_module) -> None:  # type: ignore[no-untyped-def]
    from lub.benchmarks.credit_scoring import AustralianCreditDataset, GermanCreditDataset
    from lub.benchmarks.financial_sentiment import FiQASADataset, FPBDataset

    loader_filenames = {
        "fpb": FPBDataset._FILENAME,
        "fiqa_sa": FiQASADataset._FILENAME,
        "german_credit": GermanCreditDataset._FILENAME,
        "australian_credit": AustralianCreditDataset._FILENAME,
    }
    script_filenames = {t.lub_name: t.out_filename for t in script_module._TASKS}
    for name, expected_filename in loader_filenames.items():
        assert script_filenames[name] == expected_filename, (
            f"Task {name!r}: script writes {script_filenames[name]!r} but "
            f"the loader reads {expected_filename!r} — they must match or "
            f"the loader will raise FileNotFoundError after fetch."
        )


def test_row_to_record_handles_flare_shape(script_module) -> None:  # type: ignore[no-untyped-def]
    task = script_module._TASKS[0]  # fpb
    row = {
        "id": "42",
        "query": "The sentiment is ...",
        "answer": "positive",
        "choices": ["positive", "negative", "neutral"],
        "aspect": "earnings",
    }
    record = script_module._row_to_record(task, 0, row)
    assert record["id"] == "42"
    assert record["question"] == "The sentiment is ..."
    assert record["gold_answer"] == "positive"
    assert record["aspect"] == "earnings"


def test_row_to_record_missing_question_raises(script_module) -> None:  # type: ignore[no-untyped-def]
    task = script_module._TASKS[0]
    with pytest.raises(KeyError, match="question field"):
        script_module._row_to_record(task, 0, {"answer": "positive"})


def test_row_to_record_missing_answer_raises(script_module) -> None:  # type: ignore[no-untyped-def]
    task = script_module._TASKS[0]
    with pytest.raises(KeyError, match="gold-answer"):
        script_module._row_to_record(task, 0, {"query": "x"})
