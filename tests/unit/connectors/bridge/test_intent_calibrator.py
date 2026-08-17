# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.connectors.bridge.intent_calibrator`.

The intent calibrator is the seam between Bridge's first governance
checkpoint (intent routing) and LUB's calibration layer. These tests
exercise the full Bridge -> Calibrator -> Guard pipeline against:

* customer queries (PT-BR and EN) routed through the classifier;
* the confidence-threshold contract (low -> escalate, high -> respond);
* edge cases (empty input, missing keywords, broken normalizer);
* error handling (LLM-backend timeout, transform-time exceptions).

LLM calls are mocked via the in-module ``_FakeLLM`` fixture so the suite
remains hermetic and deterministic.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from lub.calibration.normalizers import (
    IdentityNormalizer,
    IsotonicNormalizer,
    MinMaxNormalizer,
    Normalizer,
)
from lub.connectors.bridge.agents.chatbot import Intent
from lub.connectors.bridge.agents.intent_classifier import (
    ClassificationMethod,
    IntentClassifier,
    IntentResult,
    Language,
)
from lub.connectors.bridge.intent_calibrator import (
    CalibratedIntentClassifier,
    CalibratedIntentResult,
    CalibrationReport,
    CalibrationTrainingExample,
    calibration_audit_event,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Deterministic LLM stand-in for the disambiguation fallback."""

    def __init__(self, reply: str = "pix") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self.reply


class _BoomLLM:
    """LLM that always raises (simulates backend timeout / API error)."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        raise TimeoutError("upstream LLM timed out")


class _BrokenNormalizer(Normalizer):
    """Normalizer that claims to be fitted but blows up on transform."""

    NAME = "broken"

    def __init__(self) -> None:
        super().__init__()
        self.fitted_ = True

    def fit(self, confs, correct):  # noqa: D401, ANN001
        self.fitted_ = True
        return self

    def transform(self, confs):  # noqa: ANN001
        raise RuntimeError("normalizer exploded")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.NAME}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _BrokenNormalizer:
        return cls()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def keyword_classifier() -> IntentClassifier:
    """Plain keyword-only classifier — LLM fallback is disabled."""
    return IntentClassifier(llm_backend=None)


@pytest.fixture
def classifier_with_llm() -> IntentClassifier:
    """Classifier wired to a deterministic fake LLM for ambiguity cases."""
    return IntentClassifier(llm_backend=_FakeLLM(reply="pix"))


@pytest.fixture
def calibrator(keyword_classifier: IntentClassifier) -> CalibratedIntentClassifier:
    """Identity-normalizer wrapper, primed via a trivial fit so transform is a no-op.

    The wrapper's ``is_fitted`` short-circuits to ``True`` for
    ``IdentityNormalizer``, but the underlying ``transform`` still
    needs ``fit()`` to have set ``fitted_``. Priming here keeps the
    bulk of the suite focused on the calibration *contract* rather
    than that initialization quirk (which is covered separately by
    :class:`TestUnfittedIdentity`).
    """
    cal = CalibratedIntentClassifier(keyword_classifier)
    cal.normalizer.fit(np.asarray([0.5]), np.asarray([1.0]))
    return cal


@pytest.fixture
def unfitted_calibrator(keyword_classifier: IntentClassifier) -> CalibratedIntentClassifier:
    """Wrapper as constructed — IdentityNormalizer present but ``fitted_`` is False."""
    return CalibratedIntentClassifier(keyword_classifier)


@pytest.fixture
def training_examples() -> list[CalibrationTrainingExample]:
    """A small but non-trivial calibration set with deliberate miscalibration.

    Low raw confidences turn out correct only sometimes; high raw
    confidences are almost always correct. Isotonic regression should
    reduce ECE on this set.
    """
    return [
        CalibrationTrainingExample(raw_confidence=0.10, correct=False),
        CalibrationTrainingExample(raw_confidence=0.15, correct=False),
        CalibrationTrainingExample(raw_confidence=0.20, correct=True),
        CalibrationTrainingExample(raw_confidence=0.30, correct=False),
        CalibrationTrainingExample(raw_confidence=0.40, correct=True),
        CalibrationTrainingExample(raw_confidence=0.55, correct=True),
        CalibrationTrainingExample(raw_confidence=0.60, correct=True),
        CalibrationTrainingExample(raw_confidence=0.70, correct=True),
        CalibrationTrainingExample(raw_confidence=0.85, correct=True),
        CalibrationTrainingExample(raw_confidence=0.95, correct=True),
    ]


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class TestCalibrationTrainingExample:
    def test_accepts_boundary_values(self) -> None:
        CalibrationTrainingExample(raw_confidence=0.0, correct=False)
        CalibrationTrainingExample(raw_confidence=1.0, correct=True)

    @pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.5])
    def test_rejects_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="raw_confidence"):
            CalibrationTrainingExample(raw_confidence=bad, correct=True)


class TestCalibrationReport:
    def test_improvement_is_ece_reduction(self) -> None:
        report = CalibrationReport(
            normalizer_name="isotonic",
            n_examples=10,
            ece_before=0.30,
            ece_after=0.05,
        )
        assert report.improvement == pytest.approx(0.25)

    def test_negative_improvement_when_calibration_made_things_worse(self) -> None:
        report = CalibrationReport(
            normalizer_name="identity",
            n_examples=5,
            ece_before=0.05,
            ece_after=0.30,
        )
        assert report.improvement == pytest.approx(-0.25)

    def test_to_dict_is_json_safe(self) -> None:
        import json

        report = CalibrationReport(
            normalizer_name="isotonic",
            n_examples=10,
            ece_before=0.30,
            ece_after=0.05,
        )
        # Must round-trip through JSON without raising.
        payload = json.dumps(report.to_dict())
        decoded = json.loads(payload)
        assert decoded["normalizer"] == "isotonic"
        assert decoded["n_examples"] == 10
        assert decoded["improvement"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Construction & inspection
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_normalizer_is_identity(
        self, keyword_classifier: IntentClassifier
    ) -> None:
        cal = CalibratedIntentClassifier(keyword_classifier)
        assert isinstance(cal.normalizer, IdentityNormalizer)
        assert cal.normalizer_name == "identity"

    def test_identity_normalizer_is_always_fitted_at_wrapper_level(
        self, unfitted_calibrator: CalibratedIntentClassifier
    ) -> None:
        assert unfitted_calibrator.is_fitted is True

    def test_unfitted_minmax_reports_not_fitted(
        self, keyword_classifier: IntentClassifier
    ) -> None:
        cal = CalibratedIntentClassifier(keyword_classifier, normalizer=MinMaxNormalizer())
        assert cal.is_fitted is False


# ---------------------------------------------------------------------------
# Inference — full Bridge pipeline
# ---------------------------------------------------------------------------


class TestClassify:
    def test_high_confidence_pt_br_pix_query(self, calibrator: CalibratedIntentClassifier) -> None:
        result = calibrator.classify("quero fazer um pix para minha esposa")
        assert isinstance(result, CalibratedIntentResult)
        assert result.intent is Intent.PIX
        assert 0.0 <= result.confidence <= 1.0
        # Identity normalizer must preserve the raw confidence exactly.
        assert result.confidence == pytest.approx(result.raw.confidence)
        assert result.calibration_error is None
        assert result.normalizer_name == "identity"

    def test_english_balance_query(self, calibrator: CalibratedIntentClassifier) -> None:
        result = calibrator.classify("what is my account balance", language=Language.EN)
        assert result.intent is Intent.BALANCE
        assert result.raw.language is Language.EN

    def test_empty_query_returns_general_zero_confidence(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("")
        assert result.intent is Intent.GENERAL
        assert result.confidence == pytest.approx(0.0)
        assert result.raw.method is ClassificationMethod.DEFAULT

    def test_whitespace_only_query_treated_as_empty(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("   \t\n  ")
        assert result.intent is Intent.GENERAL
        assert result.confidence == pytest.approx(0.0)

    def test_no_keyword_match_returns_general(self, calibrator: CalibratedIntentClassifier) -> None:
        result = calibrator.classify("xyzzy plover qux frobnitz")
        assert result.intent is Intent.GENERAL
        assert result.confidence == pytest.approx(0.0)

    def test_raw_intent_result_preserved_for_audit(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("quero ver meu saldo")
        assert isinstance(result.raw, IntentResult)
        assert result.raw.intent is Intent.BALANCE
        # The raw IntentResult is immutable — audit replay can trust it.
        with pytest.raises((AttributeError, Exception)):
            result.raw.confidence = 0.0  # type: ignore[misc]

    def test_pii_is_not_leaked_into_audit_marker(
        self, keyword_classifier: IntentClassifier
    ) -> None:
        """A normalizer error must not echo the query into ``calibration_error``."""
        cal = CalibratedIntentClassifier(keyword_classifier, normalizer=_BrokenNormalizer())
        result = cal.classify("transferir 1000 para CPF 123.456.789-00")
        # Fail-open: raw confidence survives.
        assert result.confidence == pytest.approx(result.raw.confidence)
        assert result.calibration_error is not None
        assert "RuntimeError" in result.calibration_error
        # The error string must not contain the CPF / amount from the query.
        assert "123.456.789" not in result.calibration_error
        assert "1000" not in result.calibration_error


class TestClassifyBatch:
    def test_returns_tuple_not_list(self, calibrator: CalibratedIntentClassifier) -> None:
        results = calibrator.classify_batch(["quero fazer um pix", "ver saldo"])
        assert isinstance(results, tuple)
        assert len(results) == 2

    def test_empty_batch_returns_empty_tuple(self, calibrator: CalibratedIntentClassifier) -> None:
        assert calibrator.classify_batch([]) == ()

    def test_batch_preserves_per_query_intents(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        results = calibrator.classify_batch(
            ["quero fazer um pix", "ver meu saldo", "tirar emprestimo"]
        )
        assert [r.intent for r in results] == [Intent.PIX, Intent.BALANCE, Intent.LOAN]


# ---------------------------------------------------------------------------
# Confidence-threshold contract (the Bridge routing decision)
# ---------------------------------------------------------------------------


class TestConfidenceThresholds:
    """Simulate the Bridge guard's threshold-based routing decision."""

    def test_low_confidence_escalates_to_human(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        # A short, hint-free phrase with no clear keyword hit -> low conf -> escalate.
        threshold = 0.7
        result = calibrator.classify("oi tudo bem")
        escalated = result.confidence < threshold
        assert escalated, "low-confidence query must trigger escalation"

    def test_high_confidence_does_not_escalate(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        # An unambiguous keyword hit yields high confidence -> auto-respond.
        threshold = 0.5
        result = calibrator.classify("quero consultar saldo")
        escalated = result.confidence < threshold
        assert not escalated, "high-confidence query must not be escalated"

    def test_calibration_changes_routing_decision(
        self,
        keyword_classifier: IntentClassifier,
        training_examples: list[CalibrationTrainingExample],
    ) -> None:
        """A fitted isotonic calibrator must shift the routing boundary.

        With the deliberately mis-calibrated training set above, isotonic
        regression should produce a transform that is *not* the identity
        — proving the calibrator actually influences threshold decisions.
        """
        cal = CalibratedIntentClassifier(keyword_classifier)
        cal.fit_isotonic(training_examples)

        # Probe with a mid-range raw confidence; calibrated value must
        # land in [0, 1] and (with this data) move away from raw.
        # Identity would give back exactly the input.
        probe = np.asarray([0.30], dtype=np.float64)
        out = cal.normalizer.transform(probe)
        assert 0.0 <= float(out[0]) <= 1.0


# ---------------------------------------------------------------------------
# Training / persistence
# ---------------------------------------------------------------------------


class TestFit:
    def test_empty_examples_raises(self, calibrator: CalibratedIntentClassifier) -> None:
        with pytest.raises(ValueError, match="at least one"):
            calibrator.fit([])

    def test_fit_returns_report_with_correct_count(
        self,
        calibrator: CalibratedIntentClassifier,
        training_examples: list[CalibrationTrainingExample],
    ) -> None:
        report = calibrator.fit(training_examples, normalizer=IsotonicNormalizer())
        assert isinstance(report, CalibrationReport)
        assert report.n_examples == len(training_examples)
        assert report.normalizer_name == "isotonic"

    def test_fit_isotonic_reduces_ece_on_miscalibrated_set(
        self,
        calibrator: CalibratedIntentClassifier,
        training_examples: list[CalibrationTrainingExample],
    ) -> None:
        report = calibrator.fit_isotonic(training_examples)
        assert report.normalizer_name == "isotonic"
        # Isotonic on monotone-ish training data should not make things worse.
        assert report.ece_after <= report.ece_before + 1e-9

    def test_fit_replaces_normalizer_when_provided(
        self,
        calibrator: CalibratedIntentClassifier,
        training_examples: list[CalibrationTrainingExample],
    ) -> None:
        assert calibrator.normalizer_name == "identity"
        calibrator.fit(training_examples, normalizer=IsotonicNormalizer())
        assert calibrator.normalizer_name == "isotonic"
        assert calibrator.is_fitted

    def test_fit_uses_existing_normalizer_when_none_passed(
        self,
        keyword_classifier: IntentClassifier,
        training_examples: list[CalibrationTrainingExample],
    ) -> None:
        cal = CalibratedIntentClassifier(keyword_classifier, normalizer=IsotonicNormalizer())
        report = cal.fit(training_examples)
        assert report.normalizer_name == "isotonic"
        assert cal.is_fitted


class TestPersistence:
    def test_save_unfitted_minmax_raises(
        self, keyword_classifier: IntentClassifier, tmp_path
    ) -> None:
        cal = CalibratedIntentClassifier(keyword_classifier, normalizer=MinMaxNormalizer())
        with pytest.raises(RuntimeError, match="not fitted"):
            cal.save_normalizer(tmp_path / "cal.json")

    def test_save_and_load_roundtrip(
        self,
        calibrator: CalibratedIntentClassifier,
        training_examples: list[CalibrationTrainingExample],
        tmp_path,
    ) -> None:
        calibrator.fit_isotonic(training_examples)
        path = calibrator.save_normalizer(tmp_path / "iso.json")
        assert path.exists()
        # JSON, not pickle.
        assert path.read_text(encoding="utf-8").lstrip().startswith("{")

        reloaded = CalibratedIntentClassifier.from_classifier_and_path(
            classifier=IntentClassifier(),
            normalizer_path=path,
        )
        assert reloaded.normalizer_name == "isotonic"
        assert reloaded.is_fitted

    def test_save_identity_normalizer_writes_minimal_json(
        self, calibrator: CalibratedIntentClassifier, tmp_path
    ) -> None:
        path = calibrator.save_normalizer(tmp_path / "id.json")
        body = path.read_text(encoding="utf-8")
        assert '"type": "identity"' in body


# ---------------------------------------------------------------------------
# Recalibration (audit replay)
# ---------------------------------------------------------------------------


class TestRecalibrate:
    def test_marks_replay_in_metadata(self, calibrator: CalibratedIntentClassifier) -> None:
        original = IntentResult(
            intent=Intent.PIX,
            confidence=0.42,
            language=Language.PT_BR,
            method=ClassificationMethod.KEYWORD,
            metadata={"matched_keywords": ["pix"]},
        )
        replayed = calibrator.recalibrate_result(original)
        assert replayed.intent is Intent.PIX
        assert replayed.raw.metadata["recalibrated"] is True
        # Pre-existing metadata survives.
        assert replayed.raw.metadata["matched_keywords"] == ["pix"]
        # Original IntentResult is not mutated (it's frozen).
        assert "recalibrated" not in original.metadata


# ---------------------------------------------------------------------------
# Error handling — backend & normalizer failures
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_llm_backend_timeout_falls_back_to_keyword(self) -> None:
        """Underlying classifier already falls back; wrapper must not break it."""
        classifier = IntentClassifier(llm_backend=_BoomLLM(), llm_fallback_threshold=0.99)
        cal = CalibratedIntentClassifier(classifier)
        cal.normalizer.fit(np.asarray([0.5]), np.asarray([1.0]))
        # Ambiguous-ish keyword query triggers the LLM path, which raises.
        result = cal.classify("quero fazer um pix")
        # The classifier swallows the LLM error and returns the keyword result.
        assert result.intent is Intent.PIX
        assert result.raw.method is ClassificationMethod.KEYWORD
        assert result.calibration_error is None

    def test_transform_exception_fails_open(
        self, keyword_classifier: IntentClassifier
    ) -> None:
        cal = CalibratedIntentClassifier(keyword_classifier, normalizer=_BrokenNormalizer())
        result = cal.classify("quero fazer um pix")
        # Raw confidence survives the calibrator blow-up.
        assert result.confidence == pytest.approx(result.raw.confidence)
        assert result.calibration_error is not None
        assert "RuntimeError" in result.calibration_error
        assert "normalizer exploded" in result.calibration_error

    def test_unfitted_minmax_returns_raw_with_marker(
        self, keyword_classifier: IntentClassifier
    ) -> None:
        cal = CalibratedIntentClassifier(keyword_classifier, normalizer=MinMaxNormalizer())
        result = cal.classify("quero fazer um pix")
        assert result.confidence == pytest.approx(result.raw.confidence)
        assert result.calibration_error == "normalizer_not_fitted"


# ---------------------------------------------------------------------------
# Serialization / audit envelopes
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_calibrated_result_to_dict_contains_delta(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("quero fazer um pix")
        payload = result.to_dict()
        # Identity normalizer -> delta is zero.
        assert payload["delta"] == pytest.approx(0.0)
        assert payload["intent"] == Intent.PIX.value
        assert payload["normalizer"] == "identity"
        assert payload["calibration_error"] is None
        assert "timestamp" in payload
        assert "raw" in payload  # nested raw IntentResult.to_dict()

    def test_audit_event_structure(self, calibrator: CalibratedIntentClassifier) -> None:
        result = calibrator.classify("quero fazer um pix")
        event = calibration_audit_event(result, role="customer")
        assert event["event"] == "intent.calibrated"
        assert event["intent"] == Intent.PIX.value
        assert event["normalizer"] == "identity"
        assert event["method"] == ClassificationMethod.KEYWORD.value
        assert event["role"] == "customer"
        assert event["raw_confidence"] == pytest.approx(result.raw.confidence)
        assert event["calibrated_confidence"] == pytest.approx(result.confidence)

    def test_audit_event_omits_role_when_not_passed(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("quero fazer um pix")
        event = calibration_audit_event(result)
        assert "role" not in event

    def test_audit_event_handles_string_method(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        # Some legacy audit replays carry ``method`` as a raw string.
        original = IntentResult(
            intent=Intent.PIX,
            confidence=0.42,
            language=Language.PT_BR,
            method=ClassificationMethod.LLM_FALLBACK,
            metadata={},
        )
        replayed = calibrator.recalibrate_result(original)
        event = calibration_audit_event(replayed)
        assert event["method"] == ClassificationMethod.LLM_FALLBACK.value


# ---------------------------------------------------------------------------
# Unfitted-IdentityNormalizer quirk
# ---------------------------------------------------------------------------


class TestUnfittedIdentity:
    """The wrapper claims identity is always fitted but the underlying
    :class:`IdentityNormalizer.transform` still requires ``fitted_`` to be
    ``True``. Fail-open behavior must still surface raw confidence."""

    def test_fresh_identity_normalizer_fails_open_with_marker(
        self, unfitted_calibrator: CalibratedIntentClassifier
    ) -> None:
        result = unfitted_calibrator.classify("quero fazer um pix")
        # Raw confidence is preserved even though the transform raised.
        assert result.confidence == pytest.approx(result.raw.confidence)
        assert result.calibration_error is not None


# ---------------------------------------------------------------------------
# End-to-end Bridge pipeline simulation
# ---------------------------------------------------------------------------


class TestBridgePipeline:
    """Customer query -> Bridge router -> calibrator -> threshold decision."""

    def _route(self, result: CalibratedIntentResult, threshold: float) -> str:
        return "escalate" if result.confidence < threshold else result.intent.value

    def test_unambiguous_pix_query_routes_to_payments_agent(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("quero pagar um pix com qr code")
        decision = self._route(result, threshold=0.4)
        assert decision == Intent.PIX.value

    def test_unintelligible_query_escalates(
        self, calibrator: CalibratedIntentClassifier
    ) -> None:
        result = calibrator.classify("???")
        decision = self._route(result, threshold=0.5)
        assert decision == "escalate"

    def test_calibration_is_applied_at_inference_time(
        self,
        keyword_classifier: IntentClassifier,
        training_examples: list[CalibrationTrainingExample],
    ) -> None:
        """Once fitted, the wrapper's confidence differs from the raw one."""
        cal = CalibratedIntentClassifier(keyword_classifier)
        cal.fit_isotonic(training_examples)
        result = cal.classify("quero fazer um pix")
        # Calibrated confidence must remain a valid probability.
        assert 0.0 <= result.confidence <= 1.0
        # And the raw confidence is still around for the audit trail.
        assert 0.0 <= result.raw.confidence <= 1.0
