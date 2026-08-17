# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Phased rollout configuration with prerequisites.

Pattern 3 from ``planning/RUFLO_PATTERNS_TO_ADOPT_2026-04-25.md``.

A :class:`PhaseConfig` declares a window (``[start_week, end_week]``)
and a list of prerequisite phase ids. The :class:`Phase` predicate
wrapper answers ``is_active(week, completed_phases)`` — useful for the
calibrated banking-compliance plugin pack which lands in waves, and
for any rollout where dependencies must be respected.

Pure data + predicates. No I/O, no time-of-day awareness, no real
calendar — "week" is a bare integer the caller can interpret as a
sprint number, an ISO week, or a phase counter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PhaseConfig:
    """Declarative description of one rollout phase.

    Attributes
    ----------
    id:
        Stable identifier. Compared for prerequisite resolution.
    start_week:
        Inclusive start (lowest week number the phase is active).
    end_week:
        Inclusive end (highest week number the phase is active).
    prerequisites:
        Phase ids that must be in ``completed_phases`` before this
        phase can be considered active.
    """

    id: str
    start_week: int
    end_week: int
    prerequisites: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize prerequisites to a tuple and validate field invariants."""
        # Coerce list -> tuple for hashability.
        if not isinstance(self.prerequisites, tuple):
            object.__setattr__(self, "prerequisites", tuple(self.prerequisites))
        if not self.id:
            raise ValueError("PhaseConfig.id must be a non-empty string")
        if self.start_week > self.end_week:
            raise ValueError(
                f"PhaseConfig {self.id!r}: start_week ({self.start_week}) "
                f"> end_week ({self.end_week})"
            )


class Phase:
    """Predicate wrapper around :class:`PhaseConfig`.

    Stateless. Pass the current ``week`` and the ``completed_phases``
    set to query.
    """

    def __init__(self, config: PhaseConfig) -> None:
        """Bind the wrapper to its underlying :class:`PhaseConfig`."""
        self._config = config

    @property
    def config(self) -> PhaseConfig:
        """Return the wrapped :class:`PhaseConfig`."""
        return self._config

    @property
    def id(self) -> str:
        """Return the phase id from the wrapped config."""
        return self._config.id

    def is_active(self, week: int, completed_phases: set[str]) -> bool:
        """True iff ``week`` is in window AND all prereqs are completed."""
        in_window = self._config.start_week <= week <= self._config.end_week
        if not in_window:
            return False
        return all(p in completed_phases for p in self._config.prerequisites)

    def is_blocked(self, completed_phases: set[str]) -> bool:
        """True iff at least one prerequisite is not in ``completed_phases``."""
        return any(p not in completed_phases for p in self._config.prerequisites)

    def is_blocked_by(self, completed_phases: set[str]) -> tuple[str, ...]:
        """Return the tuple of unmet prerequisite ids.

        Empty tuple iff :meth:`is_blocked` is False.
        """
        return tuple(p for p in self._config.prerequisites if p not in completed_phases)


def active_phases(
    phases: Iterable[Phase],
    week: int,
    completed_phases: set[str],
) -> list[Phase]:
    """Filter ``phases`` down to those active at ``week`` given completed.

    Order is preserved from input.
    """
    return [p for p in phases if p.is_active(week, completed_phases)]


__all__ = [
    "PhaseConfig",
    "Phase",
    "active_phases",
]
