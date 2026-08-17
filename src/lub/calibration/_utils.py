# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared calibration utilities — extracted to break circular imports.

``metrics.py`` and ``selective.py`` both need ``_as_pair`` for input
validation. Having ``selective.py`` import from ``metrics.py`` while
``metrics.py`` lazy-imports from ``selective.py`` creates a fragile
near-circular dependency. Extracting the shared helper here breaks
the cycle cleanly.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


def _as_pair(
    confs: ArrayLike, correct: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Validate and convert ``(confs, correct)`` to a pair of 1-D float64 arrays."""
    c = np.asarray(confs, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if c.shape != y.shape:
        raise ValueError(f"confs and correct must have same shape, got {c.shape} vs {y.shape}")
    if c.size == 0:
        raise ValueError("confs/correct must be non-empty")
    if np.any((c < 0.0) | (c > 1.0)):
        raise ValueError("confs must lie in [0, 1]")
    return c, y


# np.trapezoid is numpy>=2.0; np.trapz is the back-compatible alias (deprecated
# in 2.0 but still present, scheduled for removal). Resolve the name once here
# so the rest of the calibration package can call _trapezoid(...) regardless of
# the installed numpy version. Centralizing in _utils also means a single place
# to update when numpy eventually removes the legacy name.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


__all__ = ["_as_pair", "_trapezoid"]
