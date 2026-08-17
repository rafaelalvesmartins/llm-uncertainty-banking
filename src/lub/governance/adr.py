# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Architecture Decision Records + enforcement.

An ADR is a Markdown file with a YAML front-matter block declaring the
policy invariants. At runtime, :func:`assert_policy` checks an
:class:`UncertaintyResult` against a :class:`BoundedContext` and
raises :class:`PolicyViolation` when a declared invariant is breached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lub.governance.contexts import BoundedContext
from lub.types import UncertaintyResult


class PolicyViolation(RuntimeError):
    """Raised when a runtime call violates a declared ADR invariant."""


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class ADR:
    """One decision record.

    Attributes
    ----------
    id:
        Stable identifier, e.g. ``"0001"``.
    title:
        Short human title.
    metadata:
        Parsed YAML front-matter.
    body:
        Markdown body (everything after the front-matter).
    """

    id: str
    title: str
    metadata: dict[str, Any]
    body: str

    @classmethod
    def from_path(cls, path: Path) -> ADR:
        """Load an ADR from a ``NNNN-title.md`` file."""
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise ValueError(f"ADR {path} missing YAML front-matter")
        metadata = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
        stem = path.stem
        parts = stem.split("-", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            raise ValueError(f"ADR filename must be NNNN-title.md, got {path.name}")
        return cls(id=parts[0], title=parts[1].replace("-", " "), metadata=metadata, body=body)


class ADRRegistry:
    """Directory-backed registry of ADRs."""

    def __init__(self, root: Path | str) -> None:
        """Load every ``NNNN-*.md`` ADR found under *root* into the registry."""
        self.root = Path(root)
        self._by_id: dict[str, ADR] = {}
        if self.root.exists():
            for path in sorted(self.root.glob("[0-9][0-9][0-9][0-9]-*.md")):
                adr = ADR.from_path(path)
                self._by_id[adr.id] = adr

    def get(self, id_: str) -> ADR:
        """Return the ADR registered under *id_* or raise ``KeyError``."""
        if id_ not in self._by_id:
            raise KeyError(f"No ADR registered for id {id_!r}")
        return self._by_id[id_]

    def all(self) -> dict[str, ADR]:
        """Return a shallow copy of the id-to-ADR mapping."""
        return dict(self._by_id)


def assert_policy(
    result: UncertaintyResult,
    context: BoundedContext,
    *,
    measured_ece: float | None = None,
) -> None:
    """Raise :class:`PolicyViolation` if *result* breaches *context*.

    Two checks today, extensible:

    * If the result is accepted (``not should_refuse``) its confidence
      must be high enough that a coherent ``risk_ceiling`` is still
      plausible. Concretely: ``confidence >= 1 - risk_ceiling``.
    * If *measured_ece* is provided (e.g. from
      :meth:`~lub.ledger.Ledger.replay_calibration`), it must not
      exceed :attr:`BoundedContext.calibration_target_ece`.
    """
    if not result.should_refuse:
        floor = 1.0 - float(context.risk_ceiling)
        if result.confidence < floor:
            raise PolicyViolation(
                f"Context {context.name!r}: accepted answer confidence "
                f"{result.confidence:.4f} < risk floor {floor:.4f} "
                f"(risk_ceiling={context.risk_ceiling})"
            )
    if measured_ece is not None and measured_ece > context.calibration_target_ece:
        raise PolicyViolation(
            f"Context {context.name!r}: measured ECE {measured_ece:.4f} "
            f"> target {context.calibration_target_ece}"
        )


__all__ = ["ADR", "ADRRegistry", "PolicyViolation", "assert_policy"]
