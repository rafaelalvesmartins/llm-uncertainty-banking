# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.reports.factory.

Exercises the report-generator factory: ensures each supported `report_type`
yields the corresponding concrete reporter, that unknown types raise
`ValueError`, and that imports are lazy (only the requested reporter module is
loaded).
"""

from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lub.reports.factory import create_reporter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_result() -> Any:
    """A minimal stand-in for a `BenchmarkResult`.

    The factory does not introspect results; it only forwards them to the
    chosen reporter constructor. A `MagicMock` is therefore sufficient.
    """
    r = MagicMock(name="BenchmarkResult")
    r.run_id = "run-001"
    r.estimator = "softmax"
    return r


@pytest.fixture
def results(fake_result: Any) -> list[Any]:
    """A typical multi-result payload."""
    return [fake_result, fake_result]


@pytest.fixture
def empty_results() -> list[Any]:
    """Edge case: factory must still construct a reporter from an empty list."""
    return []


# ---------------------------------------------------------------------------
# Happy paths — one test per supported report_type
# ---------------------------------------------------------------------------


def test_create_reporter_airmf_returns_airmf_reporter(results: list[Any]) -> None:
    """`report_type='airmf'` constructs an `AIRMFReporter` with the results."""
    with patch("lub.reports.renderer.AIRMFReporter") as mock_cls:
        sentinel = MagicMock(name="AIRMFReporter instance")
        mock_cls.return_value = sentinel

        reporter = create_reporter(results, report_type="airmf")

        mock_cls.assert_called_once_with(results=results)
        assert reporter is sentinel


def test_create_reporter_oscal_returns_oscal_reporter(results: list[Any]) -> None:
    """`report_type='oscal'` constructs an `OscalBatchReporter` with the results."""
    with patch("lub.reports.oscal.OscalBatchReporter") as mock_cls:
        sentinel = MagicMock(name="OscalBatchReporter instance")
        mock_cls.return_value = sentinel

        reporter = create_reporter(results, report_type="oscal")

        mock_cls.assert_called_once_with(results=results)
        assert reporter is sentinel


def test_create_reporter_giskard_returns_giskard_reporter(results: list[Any]) -> None:
    """`report_type='giskard'` constructs a `GiskardBatchReporter` with the results."""
    with patch(
        "lub.reports.giskard_reporter.GiskardBatchReporter"
    ) as mock_cls:
        sentinel = MagicMock(name="GiskardBatchReporter instance")
        mock_cls.return_value = sentinel

        reporter = create_reporter(results, report_type="giskard")

        mock_cls.assert_called_once_with(results=results)
        assert reporter is sentinel


def test_create_reporter_default_is_airmf(results: list[Any]) -> None:
    """Calling without `report_type` defaults to AIRMF — locks the public default."""
    with patch("lub.reports.renderer.AIRMFReporter") as mock_cls:
        create_reporter(results)
        mock_cls.assert_called_once_with(results=results)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_create_reporter_empty_results_still_constructs(
    empty_results: list[Any],
) -> None:
    """An empty results list is forwarded as-is — empty batches are legal."""
    with patch("lub.reports.renderer.AIRMFReporter") as mock_cls:
        create_reporter(empty_results, report_type="airmf")
        mock_cls.assert_called_once_with(results=empty_results)


def test_create_reporter_unknown_type_raises_value_error(
    results: list[Any],
) -> None:
    """Unknown `report_type` raises `ValueError` listing the supported options."""
    with pytest.raises(ValueError) as excinfo:
        create_reporter(results, report_type="bogus")  # type: ignore[arg-type]

    msg = str(excinfo.value)
    assert "bogus" in msg
    assert "airmf" in msg
    assert "oscal" in msg
    assert "giskard" in msg


@pytest.mark.parametrize("bad_type", ["", "AIRMF", "json", "html", "pdf", None])
def test_create_reporter_rejects_other_invalid_types(
    results: list[Any], bad_type: Any
) -> None:
    """Empty string, wrong case, and unrelated formats are all rejected."""
    with pytest.raises(ValueError):
        create_reporter(results, report_type=bad_type)


def test_create_reporter_unknown_type_does_not_import_any_reporter(
    results: list[Any],
) -> None:
    """An invalid `report_type` must short-circuit before any lazy import runs."""
    with (
        patch("lub.reports.renderer.AIRMFReporter") as airmf,
        patch("lub.reports.oscal.OscalBatchReporter") as oscal,
        patch("lub.reports.giskard_reporter.GiskardBatchReporter") as giskard,
        pytest.raises(ValueError),
    ):
        create_reporter(results, report_type="nope")  # type: ignore[arg-type]

    airmf.assert_not_called()
    oscal.assert_not_called()
    giskard.assert_not_called()


# ---------------------------------------------------------------------------
# Lazy-import behavior — only the requested reporter module is touched
# ---------------------------------------------------------------------------


def _purge(*module_names: str) -> None:
    """Drop modules from `sys.modules` so the next import is observable."""
    for name in module_names:
        sys.modules.pop(name, None)


def test_create_reporter_airmf_does_not_import_other_reporters(
    results: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Choosing AIRMF must not trigger OSCAL or Giskard module imports."""
    _purge(
        "lub.reports.renderer",
        "lub.reports.oscal",
        "lub.reports.giskard_reporter",
    )

    real_import = builtins.__import__
    imported: list[str] = []

    def tracking_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        imported.append(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    with patch("lub.reports.renderer.AIRMFReporter"):
        create_reporter(results, report_type="airmf")

    assert not any("oscal" in n for n in imported), imported
    assert not any("giskard" in n for n in imported), imported


def test_create_reporter_oscal_does_not_import_giskard(
    results: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Choosing OSCAL must not trigger the Giskard reporter import."""
    _purge("lub.reports.oscal", "lub.reports.giskard_reporter")

    real_import = builtins.__import__
    imported: list[str] = []

    def tracking_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        imported.append(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    with patch("lub.reports.oscal.OscalBatchReporter"):
        create_reporter(results, report_type="oscal")

    assert not any("giskard" in n for n in imported), imported


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_factory_module_exports_create_reporter_only() -> None:
    """`__all__` advertises `create_reporter` and nothing else (locks API)."""
    module = importlib.import_module("lub.reports.factory")
    assert getattr(module, "__all__", None) == ["create_reporter"]


def test_create_reporter_passes_results_by_keyword(results: list[Any]) -> None:
    """Reporter constructors are called with `results=` (keyword), not positional.

    Locks the calling convention — reporter classes are free to add new
    constructor params without breaking the factory.
    """
    with patch("lub.reports.renderer.AIRMFReporter") as mock_cls:
        create_reporter(results, report_type="airmf")

        assert mock_cls.call_args.args == ()
        assert mock_cls.call_args.kwargs == {"results": results}
