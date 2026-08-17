# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Minimal tests for ``lub.cli.answer``."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from lub.cli import app

runner = CliRunner(mix_stderr=False)


def test_version_prints_string() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() != ""


def test_version_returns_local_when_package_missing() -> None:
    from importlib import metadata as importlib_metadata

    with patch.object(
        importlib_metadata,
        "version",
        side_effect=importlib_metadata.PackageNotFoundError,
    ):
        result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.0.0+local" in result.stdout


def test_answer_success_prints_json() -> None:
    class _Result:
        answer = "42"
        confidence = 0.9
        should_refuse = False
        raw_scores = {"entropy": 0.1}

    class _Pipe:
        def answer(self, prompt: str) -> _Result:
            return _Result()

    with patch(
        "lub.cli.answer.UncertaintyPipeline.from_pretrained",
        return_value=_Pipe(),
    ):
        result = runner.invoke(
            app,
            ["answer", "What is 6*7?", "--model", "m", "--backend", "dummy"],
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["answer"] == "42"
    assert payload["confidence"] == 0.9
    assert payload["should_refuse"] is False
    assert payload["raw_scores"] == {"entropy": 0.1}


def test_answer_user_error_exits_with_user_code() -> None:
    from lub.cli import EXIT_USER

    with patch(
        "lub.cli.answer.UncertaintyPipeline.from_pretrained",
        side_effect=ValueError("bad estimator"),
    ):
        result = runner.invoke(
            app,
            ["answer", "hi", "--model", "m", "--backend", "dummy"],
        )

    assert result.exit_code == EXIT_USER
    assert "bad estimator" in result.stderr


def test_answer_internal_error_on_build_failure() -> None:
    from lub.cli import EXIT_INTERNAL

    with patch(
        "lub.cli.answer.UncertaintyPipeline.from_pretrained",
        side_effect=RuntimeError("boom"),
    ):
        result = runner.invoke(
            app,
            ["answer", "hi", "--model", "m", "--backend", "dummy"],
        )

    assert result.exit_code == EXIT_INTERNAL


def test_answer_internal_error_on_run_failure() -> None:
    from lub.cli import EXIT_INTERNAL

    class _Pipe:
        def answer(self, prompt: str):
            raise RuntimeError("kaboom")

    with patch(
        "lub.cli.answer.UncertaintyPipeline.from_pretrained",
        return_value=_Pipe(),
    ):
        result = runner.invoke(
            app,
            ["answer", "hi", "--model", "m", "--backend", "dummy"],
        )

    assert result.exit_code == EXIT_INTERNAL
