# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Structural protocol for report generators.

Allows code to depend on the report interface without importing concrete
reporter classes, enabling easier testing with mocks and cleaner separation
of concerns.
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Literal, Protocol


class ReportGenerator(Protocol):
    """Structural contract for a report generator.

    Any object exposing ``render()`` and ``save()`` methods with the correct
    signatures satisfies this protocol. Used by CLI and external code to
    type-hint report generators without depending on concrete implementations.
    """

    def render(self, format: Literal["md", "html", "json"] = "md") -> str:
        """Render the report to a string in the specified format.

        Parameters
        ----------
        format : {"md", "html", "json"}
            Output format. Default is markdown.

        Returns
        -------
        str
            The rendered report.
        """
        ...

    def save(self, path: str | Path, format: Literal["md", "html", "json"] = "md") -> Path:
        """Render the report and save it to a file.

        Parameters
        ----------
        path : str | Path
            Output file path. Parent directories are created as needed.
        format : {"md", "html", "json"}
            Output format. Default is markdown.

        Returns
        -------
        Path
            The path where the report was saved.
        """
        ...


class ReportSaveMixin:
    """Default ``save()`` for any reporter that implements ``render()``.

    Eliminates the identical 4-line ``save()`` body duplicated across
    AIRMFReporter, OscalBatchReporter, and GiskardBatchReporter.

    Subclasses MUST implement :meth:`render`. The ``@abstractmethod``
    decorator signals intent to type-checkers and IDEs even though this
    class isn't an ``ABC`` — instantiating the mixin directly would still
    hit the ``NotImplementedError`` at runtime, but a concrete subclass
    that forgets to override ``render`` now surfaces in mypy's override
    checks instead of waiting for the first call.
    """

    @abstractmethod
    def render(self, format: Literal["md", "html", "json"] = "md") -> str:  # noqa: A002
        """Render the report to a string in the specified format."""
        raise NotImplementedError  # pragma: no cover

    def save(self, path: str | Path, format: Literal["md", "html", "json"] = "md") -> Path:  # noqa: A002
        """Render and write to ``path``; create parent dirs as needed."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.render(format=format), encoding="utf-8")
        return out_path


__all__ = [
    "ReportGenerator",
    "ReportSaveMixin",
]
