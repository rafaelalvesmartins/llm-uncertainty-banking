# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for benchmarks/provenance.py — environment capture."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from lub.benchmarks.provenance import Provenance, _git_sha, _pip_freeze, _repo_version


def test_pip_freeze_returns_sorted_dict() -> None:
    pkgs = _pip_freeze()
    assert isinstance(pkgs, dict)
    assert len(pkgs) > 0
    # Should contain at least numpy (a hard dep of lub).
    assert "numpy" in pkgs
    # Sorted by key.
    assert list(pkgs.keys()) == sorted(pkgs.keys())


def test_git_sha_returns_hex_string_in_repo() -> None:
    sha = _git_sha(cwd=Path(__file__).parent.parent)
    # We're inside a git repo, so sha should be a 40-char hex string.
    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_git_sha_returns_none_for_non_repo(tmp_path: Path) -> None:
    sha = _git_sha(cwd=tmp_path)
    assert sha is None


def test_repo_version_returns_string() -> None:
    ver = _repo_version()
    assert isinstance(ver, str)
    assert len(ver) > 0


def test_repo_version_fallback_when_not_installed() -> None:
    from importlib.metadata import PackageNotFoundError

    with patch(
        "lub.benchmarks.provenance.importlib_metadata.version",
        side_effect=PackageNotFoundError("llm-uncertainty-banking"),
    ):
        ver = _repo_version()
        assert ver == "0.0.0+local"


def test_provenance_capture_returns_all_fields() -> None:
    prov = Provenance.capture()
    assert isinstance(prov.repo_version, str)
    assert prov.python_version == platform.python_version()
    assert isinstance(prov.package_versions, dict)
    assert len(prov.package_versions) > 0
    # git_sha may or may not be present depending on environment.
    assert prov.git_sha is None or len(prov.git_sha) == 40


def test_provenance_is_frozen() -> None:
    prov = Provenance.capture()
    with pytest.raises(AttributeError):
        prov.repo_version = "hacked"  # type: ignore[misc]


def test_provenance_capture_with_cwd(tmp_path: Path) -> None:
    prov = Provenance.capture(cwd=tmp_path)
    # tmp_path is not a git repo, so git_sha should be None.
    assert prov.git_sha is None
    # But the rest should still be populated.
    assert prov.python_version == platform.python_version()
    assert len(prov.package_versions) > 0
