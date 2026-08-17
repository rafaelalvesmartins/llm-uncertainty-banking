# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Calibrate :class:`IntentClassifier` confidences via ``lub.calibration``.

This connector closes the *missing seam* between Bridge's first
governance checkpoint (intent routing) and LUB's calibration layer.

Why this exists
---------------
:class:`~lub.connectors.bridge.agents.intent_classifier.IntentClassifier`
returns a ``confidence`` computed as ``top_score / total`` -- a raw
keyword-share ratio, not a calibrated probability. The Bridge platform
nevertheless

* compares this number against routing thresholds, and
* writes it verbatim into BCB 4893 / SR 11-7 audit envelopes.

If the keyword baseline is systematically over- or under-confident on a
given intent (a known failure mode for short PT-BR tokens such as a
bare ``"pix"`` substring), every downstream governance decision is
operating on a miscalibrated signal. :class:`CalibratedIntentClassifier`
fits a :class:`~lub.calibration.normalizers.Normalizer` against observed
intent accuracy and applies it at inference time, surfacing **both** the
raw and the calibrated confidence so a regulator can replay the decision
either way.

Operational contract
--------------------
* The calibrator is *additive*: the underlying classifier is never
  mutated, and the original ``IntentResult.confidence`` survives in the
  audit record. This means a calibrator can be rolled back instantly
  (drop the wrapper, keep the classifier) without losing the routing
  history.
* Calibration state serializes to JSON via the normalizer's
  ``to_dict`` / ``from_dict`` -- never pickle -- so a model-risk
  reviewer can read the fitted parameters in a text editor.
* Errors during ``transform`` degrade *open*: the raw confidence is
  returned with a ``calibration_error`` audit marker, because losing
  the routing decision is strictly worse for a banking workflow than
  serving it with a non-calibrated number that is still bounded in
  ``[0, 1]``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from numpy.typing import ArrayLike, NDArray

from lub.calibration.metrics import expected_calibration_error
from lub.calibration.normalizers import (
    IdentityNormalizer,
    IsotonicNormalizer,
    Normalizer,
    load_normalizer,
)
from lub.connectors.bridge.agents.chatbot import Intent
from lub.connectors.bridge.agents.intent_classifier import (
    ClassificationMethod,
    IntentClassifier,
    IntentResult,
    Language,
)

__all__ = [
    "CalibratedIntentClassifier",
    "CalibratedIntentResult",
    "CalibrationReport",
    "CalibrationTrainingExample",
]

_LOG = structlog.get_logger("lub.connectors.bridge.intent_calibrator")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibratedIntentResult:
    """Intent result carrying both raw and calibrated confidence.

    The original :class:`IntentResult` is preserved on ``raw`` so the
    audit trail can replay the un-calibrated decision exactly. The
    ``confidence`` attribute is the calibrated value and is what Bridge
    routing should compare against thresholds.

    Attributes
    ----------
    intent:
        Top-ranked banking intent (identical to ``raw.intent``).
    confidence:
        Calibrated confidence in ``[0, 1]``. Equals ``raw.confidence``
        when the calibrator is an :class:`IdentityNormalizer` or when
        calibration failed (see ``calibration_error``).
    raw:
        Original :class:`IntentResult` from the underlying classifier.
    normalizer_name:
        ``Normalizer.NAME`` of the fitted calibrator, recorded for the
        audit trail so a regulator can pin a decision to a specific
        calibrator artifact.
    calibration_error:
        ``None`` on the happy path. On failure, a short diagnostic
        string (never PII) explaining why the raw confidence was
        passed through unmodified.
    timestamp:
        Wall-clock time the calibration was applied. UTC, ISO-8601 in
        serialized form.
    """

    intent: Intent
    confidence: float
    raw: IntentResult
    normalizer_name: str
    calibration_error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON audit logs (BCB 4893 / SR 11-7)."""
        return {
            "intent": self.intent.value,
            "confidence": float(self.confidence),
            "raw_confidence": float(self.raw.confidence),
            "delta": float(self.confidence - self.raw.confidence),
            "normalizer": self.normalizer_name,
            "calibration_error": self.calibration_error,
            "timestamp": self.timestamp.isoformat(),
            "raw": self.raw.to_dict(),
        }


@dataclass(frozen=True)
class CalibrationTrainingExample:
    """One observed (raw_confidence, was_correct) pair used to fit a calibrator.

    Notes
    -----
    ``raw_confidence`` is the classifier's pre-calibration confidence
    (``IntentResult.confidence``); ``correct`` is a boolean ground-truth
    label supplied by a labelling pipeline -- typically derived from
    operator overrides in the call-center surface or from gold-labelled
    chatbot conversations.
    """

    raw_confidence: float
    correct: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.raw_confidence <= 1.0:
            raise ValueError(f"raw_confidence must be in [0, 1], got {self.raw_confidence!r}")


@dataclass(frozen=True)
class CalibrationReport:
    """Diagnostics emitted after :meth:`CalibratedIntentClassifier.fit`.

    Bundles the metrics a model-risk reviewer needs to sign off on a
    new calibrator: how many examples were used, what the calibration
    error was before vs. after fitting, and the normalizer's identifier.
    """

    normalizer_name: str
    n_examples: int
    ece_before: float
    ece_after: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def improvement(self) -> float:
        """ECE reduction (positive = better calibration after fit)."""
        return float(self.ece_before - self.ece_after)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the audit trail."""
        return {
            "normalizer": self.normalizer_name,
            "n_examples": int(self.n_examples),
            "ece_before": float(self.ece_before),
            "ece_after": float(self.ece_after),
            "improvement": self.improvement,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Main connector
# ---------------------------------------------------------------------------


class CalibratedIntentClassifier:
    """Wrap an :class:`IntentClassifier` with a fitted calibration normalizer.

    Parameters
    ----------
    classifier:
        Underlying :class:`IntentClassifier`. Never mutated.
    normalizer:
        A :class:`~lub.calibration.normalizers.Normalizer` instance.
        Defaults to :class:`IdentityNormalizer` (pass-through) so the
        wrapper is safe to install before any calibration data exists.
        Replace with :class:`IsotonicNormalizer` (or any other fitted
        normalizer) once you have a held-out labelled set.

    Notes
    -----
    The wrapper is intentionally *one-way*: it can only widen the audit
    trail (raw + calibrated), never narrow it. The underlying classifier
    can always be invoked directly when a caller needs the un-calibrated
    decision for back-testing.
    """

    def __init__(
        self,
        classifier: IntentClassifier,
        normalizer: Normalizer | None = None,
    ) -> None:
        self._classifier = classifier
        self._normalizer: Normalizer = normalizer or IdentityNormalizer()
        _LOG.info(
            "intent_calibrator.initialized",
            normalizer=self._normalizer.NAME,
            fitted=bool(getattr(self._normalizer, "fitted_", False)),
        )

    # ------------------------------------------------------------------ #
    # Inspection
    # ------------------------------------------------------------------ #

    @property
    def normalizer(self) -> Normalizer:
        """The fitted normalizer (read-only handle for audit / serialization)."""
        return self._normalizer

    @property
    def normalizer_name(self) -> str:
        """``Normalizer.NAME`` of the currently installed calibrator."""
        return self._normalizer.NAME

    @property
    def is_fitted(self) -> bool:
        """``True`` when the normalizer has been fitted on observed accuracy.

        An :class:`IdentityNormalizer` is always considered fitted: it
        has no parameters to learn and pass-through is its by-design
        behavior.
        """
        if isinstance(self._normalizer, IdentityNormalizer):
            return True
        return bool(getattr(self._normalizer, "fitted_", False))

    # ------------------------------------------------------------------ #
    # Inference
    # ------------------------------------------------------------------ #

    def classify(
        self,
        query: str,
        language: Language | str | None = None,
    ) -> CalibratedIntentResult:
        """Classify ``query`` and return both raw and calibrated confidence.

        The underlying classifier is called exactly once. Calibration is
        applied as a deterministic post-processing step over the raw
        confidence; the keyword / LLM-fallback decision logic is
        untouched.

        On any calibration failure, the raw confidence is returned with
        ``calibration_error`` set so the audit envelope records *why*
        the value was not calibrated -- failing open is the only safe
        option for live banking traffic.
        """
        raw = self._classifier.classify(query, language=language)
        calibrated, error = self._safe_transform(raw.confidence)
        return CalibratedIntentResult(
            intent=raw.intent,
            confidence=calibrated,
            raw=raw,
            normalizer_name=self._normalizer.NAME,
            calibration_error=error,
        )

    def classify_batch(
        self,
        queries: Sequence[str],
        language: Language | str | None = None,
    ) -> tuple[CalibratedIntentResult, ...]:
        """Vectorized convenience wrapper around :meth:`classify`.

        Returns a tuple (frozen) so audit-trail aggregators cannot
        accidentally mutate the per-query results in place.
        """
        return tuple(self.classify(q, language=language) for q in queries)

    # ------------------------------------------------------------------ #
    # Training / persistence
    # ------------------------------------------------------------------ #

    def fit(
        self,
        examples: Sequence[CalibrationTrainingExample],
        normalizer: Normalizer | None = None,
    ) -> CalibrationReport:
        """Fit ``normalizer`` (or the existing one) on observed accuracy.

        Parameters
        ----------
        examples:
            Sequence of :class:`CalibrationTrainingExample`. Typically
            assembled from a held-out labelled set where each example
            records the classifier's raw confidence and whether the
            chosen intent matched ground truth.
        normalizer:
            Optional replacement normalizer. When ``None``, the
            currently installed normalizer is re-fit. Pass an
            :class:`IsotonicNormalizer` here on the first call -- the
            constructor default is :class:`IdentityNormalizer` so that
            an un-fitted wrapper is still safe to deploy.

        Returns
        -------
        CalibrationReport
            ECE before / after the fit plus the example count. The
            report is also emitted as a structured log event so it
            lands in the standard Bridge audit pipeline.

        Raises
        ------
        ValueError
            If ``examples`` is empty.
        """
        if not examples:
            raise ValueError("fit() requires at least one training example")

        confs, correct = self._examples_to_arrays(examples)
        ece_before = float(expected_calibration_error(confs, correct))

        target = normalizer if normalizer is not None else self._normalizer
        target.fit(confs, correct)
        calibrated = np.clip(target.transform(confs), 0.0, 1.0)
        ece_after = float(expected_calibration_error(calibrated, correct))

        self._normalizer = target
        report = CalibrationReport(
            normalizer_name=target.NAME,
            n_examples=int(confs.size),
            ece_before=ece_before,
            ece_after=ece_after,
        )
        _LOG.info(
            "intent_calibrator.fitted",
            **report.to_dict(),
        )
        return report

    def fit_isotonic(
        self,
        examples: Sequence[CalibrationTrainingExample],
    ) -> CalibrationReport:
        """Convenience: install a fresh :class:`IsotonicNormalizer` and fit.

        Isotonic regression is the recommended default for the intent
        classifier's keyword-share confidence: it is monotonic (so the
        relative ranking of intents survives calibration) and makes no
        parametric assumption about the miscalibration shape.
        """
        return self.fit(examples, normalizer=IsotonicNormalizer())

    def save_normalizer(self, path: str | Path) -> Path:
        """Persist the fitted normalizer to ``path`` as JSON.

        Returns the resolved :class:`Path` so the caller can attach it
        to a deployment manifest without re-computing the location.
        """
        if not self.is_fitted:
            raise RuntimeError(
                f"normalizer {self._normalizer.NAME!r} is not fitted; "
                "call fit() before save_normalizer()."
            )
        return self._normalizer.save(path)

    @classmethod
    def from_classifier_and_path(
        cls,
        classifier: IntentClassifier,
        normalizer_path: str | Path,
    ) -> CalibratedIntentClassifier:
        """Construct a wrapper, loading the normalizer JSON from disk.

        This is the production entry point: a deployment script points
        at a calibrator artifact checked into the model registry and
        gets back a ready-to-serve wrapper without ever touching the
        normalizer's internal state.
        """
        normalizer = load_normalizer(normalizer_path)
        return cls(classifier=classifier, normalizer=normalizer)

    # ------------------------------------------------------------------ #
    # Replay helpers (audit support)
    # ------------------------------------------------------------------ #

    def recalibrate_result(self, raw: IntentResult) -> CalibratedIntentResult:
        """Apply the current calibrator to a stored :class:`IntentResult`.

        Useful when replaying historical audit records against a newer
        calibrator -- the original keyword / LLM-fallback decision is
        preserved, only the confidence scale changes. The returned
        ``raw`` field is exactly the input, and a ``recalibrated``
        marker is added to the input's metadata so that a reviewer can
        spot replay records in the audit lake.
        """
        annotated_raw = replace(
            raw,
            method=raw.method,
            metadata={**raw.metadata, "recalibrated": True},
        )
        calibrated, error = self._safe_transform(raw.confidence)
        return CalibratedIntentResult(
            intent=raw.intent,
            confidence=calibrated,
            raw=annotated_raw,
            normalizer_name=self._normalizer.NAME,
            calibration_error=error,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _safe_transform(self, raw_confidence: float) -> tuple[float, str | None]:
        """Apply the normalizer to a scalar confidence, failing open."""
        if not self.is_fitted:
            return float(raw_confidence), "normalizer_not_fitted"
        try:
            arr: NDArray[np.float64] = np.asarray([raw_confidence], dtype=np.float64)
            out = self._normalizer.transform(arr)
            value = float(np.clip(out[0], 0.0, 1.0))
        except Exception as exc:  # noqa: BLE001 -- fail open on any normalizer error
            _LOG.error(
                "intent_calibrator.transform_error",
                normalizer=self._normalizer.NAME,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return float(raw_confidence), f"{type(exc).__name__}: {exc}"
        return value, None

    @staticmethod
    def _examples_to_arrays(
        examples: Sequence[CalibrationTrainingExample],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Pack training examples into numpy arrays the normalizer accepts."""
        confs_list: list[float] = [float(e.raw_confidence) for e in examples]
        correct_list: list[float] = [1.0 if e.correct else 0.0 for e in examples]
        confs: ArrayLike = np.asarray(confs_list, dtype=np.float64)
        correct: ArrayLike = np.asarray(correct_list, dtype=np.float64)
        return np.asarray(confs, dtype=np.float64), np.asarray(correct, dtype=np.float64)


# ---------------------------------------------------------------------------
# Audit-trail adapter
# ---------------------------------------------------------------------------


def calibration_audit_event(
    result: CalibratedIntentResult,
    *,
    role: str | None = None,
) -> Mapping[str, Any]:
    """Build a structured audit event for a calibrated intent decision.

    Drop-in for :attr:`~lub.connectors.bridge.BridgeResult.audit_trail`:
    Bridge can append the returned mapping verbatim so the BCB 4893
    pack records the calibrator name, the raw vs. calibrated delta, and
    any calibration error -- the three fields a model-risk reviewer
    needs to reproduce a routing decision after the fact.
    """
    event = {
        "event": "intent.calibrated",
        "intent": result.intent.value,
        "raw_confidence": float(result.raw.confidence),
        "calibrated_confidence": float(result.confidence),
        "delta": float(result.confidence - result.raw.confidence),
        "normalizer": result.normalizer_name,
        "method": result.raw.method.value
        if isinstance(result.raw.method, ClassificationMethod)
        else str(result.raw.method),
        "calibration_error": result.calibration_error,
        "timestamp": result.timestamp.isoformat(),
    }
    if role is not None:
        event["role"] = role
    return event
