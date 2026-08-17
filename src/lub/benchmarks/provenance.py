# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Run-time provenance capture for benchmark records.

:class:`Provenance` bundles the three pieces of environmental metadata
that ``lub repro`` consults to re-run a benchmark: the installed package
version, the git SHA at the time of the run, and a full ``pip freeze``
dictionary. Separating this from the benchmark runner keeps the runner
focused on iteration + scoring and makes provenance independently
unit-testable without spinning up a pipeline.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path


def _pip_freeze() -> dict[str, str]:
    """Installed-package versions via ``importlib.metadata``, sorted."""
    pkgs: dict[str, str] = {}
    for dist in importlib_metadata.distributions():
        try:
            name = dist.metadata["Name"]
        except (KeyError, TypeError):
            continue
        if name:
            pkgs[name] = dist.version
    return dict(sorted(pkgs.items()))


def _git_sha(cwd: Path | None = None) -> str | None:
    """Current git SHA at ``cwd``, or ``None`` if not in a repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    sha = out.stdout.strip()
    return sha or None


def _repo_version() -> str:
    """Installed ``llm-uncertainty-banking`` version, or ``0.0.0+local``."""
    try:
        return importlib_metadata.version("llm-uncertainty-banking")
    except importlib_metadata.PackageNotFoundError:
        return "0.0.0+local"


@dataclass(frozen=True)
class Provenance:
    """Immutable snapshot of run-time environment metadata."""

    repo_version: str
    python_version: str
    package_versions: dict[str, str]
    git_sha: str | None

    @classmethod
    def capture(cls, *, cwd: Path | None = None) -> Provenance:
        """Gather provenance from the current environment."""
        return cls(
            repo_version=_repo_version(),
            python_version=platform.python_version(),
            package_versions=_pip_freeze(),
            git_sha=_git_sha(cwd=cwd),
        )


__all__ = ["Provenance"]
