# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.runtime.protocols`` (pass 26.5 decoupling refinement)."""

from __future__ import annotations

from dataclasses import dataclass

from lub.runtime.protocols import (
    AdapterLabel,
    AuditKey,
    RefusalAction,
    UncertaintyEstimatorProtocol,
)

# ---------------------------------------------------------------------------
# UncertaintyEstimatorProtocol -- typed surface
# ---------------------------------------------------------------------------


class _CanonicalEstimator:
    """Implements the canonical (prompt, output) signature."""

    def score(self, prompt, output):
        return 0.85


class _ReturnsDataclass:
    """Returns an object with .confidence."""

    def score(self, prompt, output):
        @dataclass
        class _R:
            confidence: float

        return _R(confidence=0.65)


class _ReturnsDict:
    """Returns a dict with confidence key."""

    def score(self, prompt, output):
        return {"confidence": 0.42}


class _NotAnEstimator:
    """Has no score method."""

    pass


def test_canonical_estimator_satisfies_protocol():
    assert isinstance(_CanonicalEstimator(), UncertaintyEstimatorProtocol)


def test_dataclass_returning_estimator_satisfies_protocol():
    assert isinstance(_ReturnsDataclass(), UncertaintyEstimatorProtocol)


def test_dict_returning_estimator_satisfies_protocol():
    assert isinstance(_ReturnsDict(), UncertaintyEstimatorProtocol)


def test_object_without_score_does_not_satisfy_protocol():
    assert not isinstance(_NotAnEstimator(), UncertaintyEstimatorProtocol)


# ---------------------------------------------------------------------------
# AuditKey constants
# ---------------------------------------------------------------------------


def test_audit_keys_are_strings_not_methods():
    assert AuditKey.ADAPTER == "adapter"
    assert AuditKey.ORCHESTRATOR_AGENT == "orchestrator_agent"
    assert AuditKey.UNCERTAINTY == "uncertainty"
    assert AuditKey.UPSTREAM_ERROR == "upstream_error"
    assert AuditKey.REFUSED == "refused"
    assert AuditKey.LAST_CONFIDENCE == "last_confidence"


def test_audit_keys_unique():
    """Every AuditKey value should be distinct (no accidental aliases)."""
    keys = [
        getattr(AuditKey, attr)
        for attr in dir(AuditKey)
        if not attr.startswith("_")
    ]
    assert len(keys) == len(set(keys)), f"Duplicate audit keys: {keys}"


# ---------------------------------------------------------------------------
# RefusalAction defaults
# ---------------------------------------------------------------------------


def test_refusal_action_defaults():
    assert RefusalAction.REQUIRES_HUMAN_REVIEW == "REQUIRES_HUMAN_REVIEW"
    assert RefusalAction.REDACTED == "[REDACTED]"
    assert RefusalAction.OMIT == "OMIT"


# ---------------------------------------------------------------------------
# AdapterLabel
# ---------------------------------------------------------------------------


def test_adapter_label_value():
    assert AdapterLabel.ORCHESTRATOR == "orchestrator"
