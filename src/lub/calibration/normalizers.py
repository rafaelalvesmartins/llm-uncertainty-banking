# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Confidence normalizers with sklearn-style fit / transform / save / load.

A normalizer takes raw estimator confidences (which may live on any
scale — log-probabilities, entropies, agreement fractions) and fits a
mapping onto empirical accuracy using a held-out calibration set. The
fitted mapping is then frozen and applied to fresh confidences at
inference time. The API mirrors sklearn's ``fit(X, y)`` /
``transform(X)`` contract, but every normalizer in this module is
implemented in pure numpy so that a model-risk reviewer can audit the
calibrator end-to-end without pulling in sklearn or torch.

All normalizers serialize to plain JSON via :meth:`to_dict` /
:meth:`from_dict` — not pickle — so persisted calibrators are
human-readable and safe to check into a compliance audit trail.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from numpy.typing import ArrayLike, NDArray

_LOG = structlog.get_logger("lub.calibration.normalizers")


def _as_float_pair(
    confs: ArrayLike,
    correct: ArrayLike,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    c = np.asarray(confs, dtype=np.float64).ravel()
    y = np.asarray(correct, dtype=np.float64).ravel()
    if c.shape != y.shape:
        raise ValueError(f"confs and correct must have same shape, got {c.shape} vs {y.shape}")
    if c.size == 0:
        raise ValueError("confs/correct must be non-empty")
    return c, y


def _as_floats(confs: ArrayLike) -> NDArray[np.float64]:
    return np.asarray(confs, dtype=np.float64).ravel()


def _clip01(a: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(np.clip(a, 0.0, 1.0), dtype=np.float64)


class Normalizer(ABC):
    """Abstract sklearn-style confidence normalizer.

    Subclasses must implement :meth:`fit`, :meth:`transform`,
    :meth:`to_dict`, and :meth:`from_dict`. The ``fitted_`` flag is
    maintained by the base class so all subclasses share the same
    "must call fit before transform" invariant.
    """

    NAME: str = "normalizer"

    def __init__(self) -> None:
        self.fitted_: bool = False

    @abstractmethod
    def fit(self, confs: ArrayLike, correct: ArrayLike) -> Normalizer:
        """Fit the mapping from raw confidence to empirical accuracy."""

    @abstractmethod
    def transform(self, confs: ArrayLike) -> NDArray[np.float64]:
        """Apply the fitted mapping. Returns calibrated confs in ``[0, 1]``."""

    def fit_transform(
        self,
        confs: ArrayLike,
        correct: ArrayLike,
    ) -> NDArray[np.float64]:
        """Fit on ``(confs, correct)`` and return the transformed confs."""
        self.fit(confs, correct)
        return self.transform(confs)

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialize fitted state to a JSON-safe dict (no pickle)."""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> Normalizer:
        """Rebuild a fitted normalizer from a :meth:`to_dict` payload."""

    def save(self, path: str | Path) -> Path:
        """Write the fitted normalizer to ``path`` as JSON."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), sort_keys=True), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: str | Path) -> Normalizer:
        """Load a fitted normalizer from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def _require_fitted(self) -> None:
        if not self.fitted_:
            raise RuntimeError(f"{type(self).__name__}.fit must be called before transform")


class IdentityNormalizer(Normalizer):
    """Pass-through baseline — useful for A/B comparing calibrators."""

    NAME = "identity"

    def fit(self, confs: ArrayLike, correct: ArrayLike) -> IdentityNormalizer:
        """Validate inputs and mark the normalizer fitted; no parameters learned."""
        _as_float_pair(confs, correct)
        self.fitted_ = True
        return self

    def transform(self, confs: ArrayLike) -> NDArray[np.float64]:
        """Return ``confs`` clipped to ``[0, 1]`` unchanged."""
        self._require_fitted()
        return _clip01(_as_floats(confs))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict containing only the type tag."""
        return {"type": self.NAME}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityNormalizer:
        """Rebuild an :class:`IdentityNormalizer` from a :meth:`to_dict` payload."""
        if data.get("type") != cls.NAME:
            raise ValueError(f"unexpected type tag {data.get('type')!r}")
        inst = cls()
        inst.fitted_ = True
        return inst


class MinMaxNormalizer(Normalizer):
    """Affine rescale to ``[0, 1]`` using observed min / max on the fit set.

    Appropriate for estimators whose raw output is unbounded (e.g. raw
    entropy values). Extreme values seen at inference time are clipped.
    """

    NAME = "minmax"

    def __init__(self) -> None:
        super().__init__()
        self.min_: float = 0.0
        self.max_: float = 1.0

    def fit(self, confs: ArrayLike, correct: ArrayLike) -> MinMaxNormalizer:
        """Record observed min/max of ``confs`` as the affine rescale endpoints."""
        c, _ = _as_float_pair(confs, correct)
        self.min_ = float(c.min())
        self.max_ = float(c.max())
        if self.max_ <= self.min_:
            self.max_ = self.min_ + 1e-12
        self.fitted_ = True
        return self

    def transform(self, confs: ArrayLike) -> NDArray[np.float64]:
        """Affinely rescale ``confs`` to ``[0, 1]`` using fitted min/max, then clip."""
        self._require_fitted()
        c = _as_floats(confs)
        scaled = (c - self.min_) / (self.max_ - self.min_)
        return _clip01(scaled)

    def to_dict(self) -> dict[str, Any]:
        """Serialize fitted ``min_`` / ``max_`` to a JSON-safe dict."""
        return {"type": self.NAME, "min": self.min_, "max": self.max_}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MinMaxNormalizer:
        """Rebuild a :class:`MinMaxNormalizer` from a :meth:`to_dict` payload."""
        if data.get("type") != cls.NAME:
            raise ValueError(f"unexpected type tag {data.get('type')!r}")
        inst = cls()
        inst.min_ = float(data["min"])
        inst.max_ = float(data["max"])
        inst.fitted_ = True
        return inst


class BinnedPCCNormalizer(Normalizer):
    """Per-bin Platt-like correction: map conf to empirical accuracy of its bin.

    Fits equal-width bins on ``[0, 1]`` from the calibration set and
    stores each bin's empirical accuracy. At transform time a new
    confidence is snapped to its bin and the stored accuracy is
    returned. Empty bins fall back to the global mean accuracy.

    "Binned PCC" follows the naming in LM-Polygraph's normalizer suite
    (Fadeeva et al. 2023); the underlying idea is the classical
    histogram calibrator from Zadrozny & Elkan (2001).
    """

    NAME = "binned_pcc"

    def __init__(self, n_bins: int = 15) -> None:
        super().__init__()
        if n_bins < 1:
            raise ValueError(f"n_bins must be >= 1, got {n_bins}")
        self.n_bins = n_bins
        self.bin_acc_: NDArray[np.float64] = np.zeros(0, dtype=np.float64)
        self.global_acc_: float = 0.0

    def _edges(self) -> NDArray[np.float64]:
        return np.asarray(np.linspace(0.0, 1.0, self.n_bins + 1), dtype=np.float64)

    def _bin_indices(self, c: NDArray[np.float64]) -> NDArray[np.intp]:
        edges = self._edges()[1:-1]
        return np.asarray(
            np.clip(np.digitize(c, edges, right=False), 0, self.n_bins - 1),
            dtype=np.intp,
        )

    def fit(self, confs: ArrayLike, correct: ArrayLike) -> BinnedPCCNormalizer:
        """Compute per-bin empirical accuracy on ``(confs, correct)``."""
        c, y = _as_float_pair(confs, correct)
        if np.any((c < 0.0) | (c > 1.0)):
            raise ValueError("binned_pcc requires confs in [0, 1]")
        idx = self._bin_indices(c)
        counts = np.bincount(idx, minlength=self.n_bins).astype(np.float64)
        sums = np.bincount(idx, weights=y, minlength=self.n_bins).astype(np.float64)
        global_acc = float(y.mean())
        bin_acc = np.full(self.n_bins, global_acc, dtype=np.float64)
        nonempty = counts > 0
        bin_acc[nonempty] = sums[nonempty] / counts[nonempty]
        self.bin_acc_ = bin_acc
        self.global_acc_ = global_acc
        self.fitted_ = True
        return self

    def transform(self, confs: ArrayLike) -> NDArray[np.float64]:
        """Snap each conf to its bin and return the bin's empirical accuracy."""
        self._require_fitted()
        c = _clip01(_as_floats(confs))
        idx = self._bin_indices(c)
        return _clip01(self.bin_acc_[idx])

    def to_dict(self) -> dict[str, Any]:
        """Serialize bin count, per-bin accuracies, and global accuracy to JSON."""
        return {
            "type": self.NAME,
            "n_bins": self.n_bins,
            "bin_acc": self.bin_acc_.tolist(),
            "global_acc": self.global_acc_,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BinnedPCCNormalizer:
        """Rebuild a :class:`BinnedPCCNormalizer` from a :meth:`to_dict` payload."""
        if data.get("type") != cls.NAME:
            raise ValueError(f"unexpected type tag {data.get('type')!r}")
        inst = cls(n_bins=int(data["n_bins"]))
        inst.bin_acc_ = np.asarray(data["bin_acc"], dtype=np.float64)
        inst.global_acc_ = float(data["global_acc"])
        inst.fitted_ = True
        return inst


class IsotonicNormalizer(Normalizer):
    """Isotonic regression via the pool-adjacent-violators (PAV) algorithm.

    Fits a monotone non-decreasing stepwise mapping from sorted raw
    confidences to empirical accuracy. Uses Ayer et al.'s classical PAV
    procedure; no sklearn. At transform time, new confidences are
    piecewise-linearly interpolated between fitted breakpoints. Out-of-
    range values are clipped to the nearest breakpoint.

    Reference: Zadrozny & Elkan (2002), "Transforming Classifier Scores
    into Accurate Multiclass Probability Estimates", KDD 2002.
    """

    NAME = "isotonic"

    def __init__(self) -> None:
        super().__init__()
        self.x_: NDArray[np.float64] = np.zeros(0, dtype=np.float64)
        self.y_: NDArray[np.float64] = np.zeros(0, dtype=np.float64)

    @staticmethod
    def _pav(y: NDArray[np.float64]) -> NDArray[np.float64]:
        """Pool-adjacent-violators on an already-sorted sequence."""
        n = y.size
        levels = y.astype(np.float64).copy()
        weights = np.ones(n, dtype=np.float64)
        i = 0
        while i < n - 1:
            if levels[i] <= levels[i + 1]:
                i += 1
                continue
            total_w = weights[i] + weights[i + 1]
            pooled = (levels[i] * weights[i] + levels[i + 1] * weights[i + 1]) / total_w
            levels[i] = pooled
            weights[i] = total_w
            # Collapse position i+1 by shifting the tail left.
            levels[i + 1 : n - 1] = levels[i + 2 : n]
            weights[i + 1 : n - 1] = weights[i + 2 : n]
            n -= 1
            if i > 0:
                i -= 1
        # Expand pooled runs back to per-sample levels.
        out = np.empty_like(y)
        pos = 0
        for k in range(n):
            run = int(weights[k])
            out[pos : pos + run] = levels[k]
            pos += run
        return out

    def fit(self, confs: ArrayLike, correct: ArrayLike) -> IsotonicNormalizer:
        """Fit a monotone stepwise mapping from sorted ``confs`` to accuracy via PAV."""
        c, y = _as_float_pair(confs, correct)
        order = np.argsort(c, kind="mergesort")
        x_sorted = c[order]
        y_sorted = y[order]
        y_pav = self._pav(y_sorted)
        # Deduplicate x values — keep the last (highest-fit) accuracy for each.
        keep = np.ones(x_sorted.size, dtype=bool)
        if x_sorted.size >= 2:
            keep[:-1] = x_sorted[:-1] != x_sorted[1:]
        self.x_ = x_sorted[keep]
        self.y_ = _clip01(y_pav[keep])
        self.fitted_ = True
        return self

    def transform(self, confs: ArrayLike) -> NDArray[np.float64]:
        """Piecewise-linearly interpolate ``confs`` against the fitted PAV breakpoints."""
        self._require_fitted()
        c = _as_floats(confs)
        if self.x_.size == 0:
            return _clip01(c)
        interp = np.interp(c, self.x_, self.y_)
        return _clip01(np.asarray(interp, dtype=np.float64))

    def to_dict(self) -> dict[str, Any]:
        """Serialize fitted breakpoint arrays ``x_`` / ``y_`` to a JSON-safe dict."""
        return {"type": self.NAME, "x": self.x_.tolist(), "y": self.y_.tolist()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IsotonicNormalizer:
        """Rebuild an :class:`IsotonicNormalizer` from a :meth:`to_dict` payload."""
        if data.get("type") != cls.NAME:
            raise ValueError(f"unexpected type tag {data.get('type')!r}")
        inst = cls()
        inst.x_ = np.asarray(data["x"], dtype=np.float64)
        inst.y_ = np.asarray(data["y"], dtype=np.float64)
        inst.fitted_ = True
        return inst


class QuantileNormalizer(Normalizer):
    """Rank-based normalizer: map conf to its empirical quantile on the fit set.

    Robust to outliers and unbounded raw scores; distorts the absolute
    scale so should be paired with a calibration metric like ECE that
    is insensitive to monotone rescaling, not raw Brier score.
    """

    NAME = "quantile"

    def __init__(self) -> None:
        super().__init__()
        self.sorted_: NDArray[np.float64] = np.zeros(0, dtype=np.float64)

    def fit(self, confs: ArrayLike, correct: ArrayLike) -> QuantileNormalizer:
        """Store the sorted fit-set confidences as the empirical quantile lookup."""
        c, _ = _as_float_pair(confs, correct)
        self.sorted_ = np.sort(c).astype(np.float64)
        self.fitted_ = True
        return self

    def transform(self, confs: ArrayLike) -> NDArray[np.float64]:
        """Return each conf's empirical quantile in ``[0, 1]`` against the fit set."""
        self._require_fitted()
        c = _as_floats(confs)
        n = self.sorted_.size
        if n == 0:
            return _clip01(c)
        ranks = np.searchsorted(self.sorted_, c, side="right")
        return _clip01(np.asarray(ranks / n, dtype=np.float64))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the sorted fit-set array to a JSON-safe dict."""
        return {"type": self.NAME, "sorted": self.sorted_.tolist()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuantileNormalizer:
        """Rebuild a :class:`QuantileNormalizer` from a :meth:`to_dict` payload."""
        if data.get("type") != cls.NAME:
            raise ValueError(f"unexpected type tag {data.get('type')!r}")
        inst = cls()
        inst.sorted_ = np.asarray(data["sorted"], dtype=np.float64)
        inst.fitted_ = True
        return inst


_REGISTRY: dict[str, type[Normalizer]] = {
    IdentityNormalizer.NAME: IdentityNormalizer,
    MinMaxNormalizer.NAME: MinMaxNormalizer,
    BinnedPCCNormalizer.NAME: BinnedPCCNormalizer,
    IsotonicNormalizer.NAME: IsotonicNormalizer,
    QuantileNormalizer.NAME: QuantileNormalizer,
}


def load_normalizer(path: str | Path) -> Normalizer:
    """Load any fitted normalizer from ``path`` by dispatching on the type tag."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tag = data.get("type")
    try:
        cls = _REGISTRY[tag]
    except KeyError as exc:
        raise ValueError(
            f"unknown normalizer type tag {tag!r}; registered: {sorted(_REGISTRY)}"
        ) from exc
    return cls.from_dict(data)


__all__ = [
    "BinnedPCCNormalizer",
    "IdentityNormalizer",
    "IsotonicNormalizer",
    "MinMaxNormalizer",
    "Normalizer",
    "QuantileNormalizer",
    "load_normalizer",
]
