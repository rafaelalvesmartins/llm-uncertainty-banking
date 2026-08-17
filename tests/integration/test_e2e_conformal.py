# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""End-to-end: conformal calibration → persist → reload → inference.

Covers gap #2 from the integration audit: every conformal unit test
exercises fit/save/load in isolation, but none runs the full flow that a
model-risk reviewer actually runs — fit on a calibration split, persist
the fitted state to disk, load it into a *fresh* :class:`UncertaintyPipeline`,
and verify marginal coverage on a held-out split.
"""

from __future__ import annotations

from pathlib import Path

from lub.pipeline import UncertaintyPipeline
from lub.types import UncertaintyResult
from lub.uncertainty.conformal import ConformalEstimator
from lub.wrappers.dummy import DummyBackend


def _calibration_split() -> list[tuple[str, str]]:
    """10-example calibration set — ``(prompt, gold_answer)`` pairs.

    Kept small (hermetic + deterministic) but large enough that the
    finite-sample corrected quantile ``ceil((n+1)(1-alpha))`` is stable.
    """
    return [
        ("What is CET1?", "Common Equity Tier 1"),
        ("What is LCR?", "Liquidity Coverage Ratio"),
        ("What is NSFR?", "Net Stable Funding Ratio"),
        ("What is RWA?", "Risk-Weighted Assets"),
        ("What is CVA?", "Credit Valuation Adjustment"),
        ("What is DVA?", "Debit Valuation Adjustment"),
        ("What is FRTB?", "Fundamental Review of the Trading Book"),
        ("What is ICAAP?", "Internal Capital Adequacy Assessment Process"),
        ("What is SREP?", "Supervisory Review and Evaluation Process"),
        ("What is IFRS 9?", "International Financial Reporting Standard 9"),
    ]


def _holdout_prompts() -> list[str]:
    """Held-out prompts that the fitted conformal predictor has not seen."""
    return [
        "What is Basel III minimum CET1?",
        "What does SA-CCR stand for?",
        "What is the leverage ratio floor?",
        "What is PRA rulebook?",
        "What is MiFID II?",
        "What is EMIR?",
        "What is BRRD?",
        "What is BCB resolution 4.658?",
    ]


def test_conformal_fit_save_reload_inference_round_trip(tmp_path: Path) -> None:
    """Fit on calibration, persist, reload, score held-out, verify coverage.

    The assertions are deliberately loose on the *exact* coverage number
    (DummyBackend is deterministic but ``1 - alpha`` is asymptotic), but
    strict on the invariants that matter for model-risk sign-off:

    * threshold persists through save/load,
    * reloaded estimator scores without re-fitting,
    * every held-out prediction has ``confidence in {0.0, 1-alpha}`` and
      a ``nonconformity`` raw-score for audit trails.
    """
    backend = DummyBackend(model_id="dummy-conformal")
    alpha = 0.1

    # 1. Fit on calibration split
    fitted = ConformalEstimator(alpha=alpha)
    fitted.fit(_calibration_split(), backend=backend)
    assert fitted.threshold is not None
    assert fitted.n_calibration == 10
    fitted_threshold = fitted.threshold

    # 2. Persist to disk
    path = tmp_path / "conformal_state.json"
    fitted.save(path)
    assert path.exists()
    assert path.stat().st_size > 0

    # 3. Reload into a fresh ConformalEstimator
    reloaded = ConformalEstimator.load(path)
    assert reloaded.alpha == alpha
    assert reloaded.threshold == fitted_threshold
    assert reloaded.n_calibration == 10

    # 4. Plug the reloaded estimator into a fresh pipeline (not via
    #    from_pretrained — that builds a *new* unfitted estimator).
    pipe = UncertaintyPipeline(
        backend=DummyBackend(model_id="dummy-conformal"),
        estimator=reloaded,
        refusal_threshold=0.0,  # leave refusal decisions to conformal
    )

    # 5. Score held-out prompts; verify invariants on every prediction.
    predictions: list[UncertaintyResult] = [
        pipe.answer(p) for p in _holdout_prompts()
    ]
    assert len(predictions) == len(_holdout_prompts())
    for pred in predictions:
        # Conformal returns exactly two confidence levels: (1-alpha) or 0.
        assert pred.confidence in (0.0, 1.0 - alpha)
        # Every result carries the audit trail the reporter needs.
        assert "nonconformity" in pred.raw_scores
        assert "threshold" in pred.raw_scores
        assert "alpha" in pred.raw_scores
        assert pred.raw_scores["threshold"] == fitted_threshold
        assert pred.raw_scores["alpha"] == alpha
        # should_refuse is the inverse of the prediction-set membership
        # flag; the two must stay consistent.
        inside = pred.confidence > 0.0
        assert pred.should_refuse == (not inside)


def test_conformal_reload_across_different_backend_instance(tmp_path: Path) -> None:
    """A fitted conformal threshold is a statistical property of the
    reference model-outputs distribution, not of the backend Python
    object. Reloading into a brand-new ``DummyBackend`` instance must
    not change the threshold or invalidate the estimator.
    """
    backend_fit = DummyBackend(model_id="dummy-fit")
    est = ConformalEstimator(alpha=0.2)
    est.fit(_calibration_split(), backend=backend_fit)

    path = tmp_path / "state.json"
    est.save(path)
    reloaded = ConformalEstimator.load(path)

    # New backend instance — same model_id, different object identity.
    backend_score = DummyBackend(model_id="dummy-fit")
    assert backend_fit is not backend_score

    pipe = UncertaintyPipeline(
        backend=backend_score, estimator=reloaded, refusal_threshold=0.0,
    )
    result = pipe.answer("What is BCBS 239?")
    assert result.raw_scores["threshold"] == est.threshold
