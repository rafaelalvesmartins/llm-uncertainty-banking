# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""The nightly verdict is one rule, shared by every caller.

``lub challenge-nightly`` and the Bridge console both need to answer "is this
deployment's calibration acceptable right now". Two implementations of that
question would drift apart, and the one that drifts is the one nobody reruns.
So the rule lives here and both call it.

Tri-state on purpose: PASS, FAIL, and INCONCLUSIVE. "We could not measure" is
different evidence from "we measured a breach", and collapsing the two is how
a governance check becomes fail-open — an empty or mispointed ledger reads as
validated.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lub.challenge.nightly import ChallengeVerdict, run_nightly_challenge
from lub.governance.contexts import default_registry
from lub.ledger import Ledger


@pytest.fixture()
def context():  # noqa: ANN201 -- BoundedContext, kept implicit to avoid the import
    return default_registry().get("regulatory-qa")


def _ledger(tmp_path: Path, name: str, *, n: int, confidence: float, correct: bool) -> Path:
    p = tmp_path / f"{name}.sqlite"
    with Ledger(p) as led:
        for i in range(n):
            q = led.log_query(prompt=f"q-{i}", domain="regulatory")
            a = led.log_answer(query_id=q, model="m", backend="dummy", answer=f"a-{i}", cost=0.0)
            led.log_score(answer_id=a, method="confidence", value=confidence)
            led.update_outcome(answer_id=a, correct=correct, ground_truth=f"a-{i}")
    return p


@pytest.fixture()
def calibrated(tmp_path: Path) -> Iterator[Path]:
    yield _ledger(tmp_path, "ok", n=40, confidence=0.98, correct=True)


@pytest.fixture()
def drifted(tmp_path: Path) -> Iterator[Path]:
    yield _ledger(tmp_path, "bad", n=40, confidence=0.99, correct=False)


# --- the three states -------------------------------------------------------


def test_calibrated_deployment_passes(calibrated: Path, context) -> None:  # noqa: ANN001
    with Ledger(calibrated) as led:
        v = run_nightly_challenge(led, context)

    assert isinstance(v, ChallengeVerdict)
    assert v.status == "PASS"
    assert v.n_samples == 40
    assert v.measured_ece is not None and v.measured_ece < v.target_ece


def test_confident_and_wrong_fails_with_the_numbers_attached(drifted: Path, context) -> None:  # noqa: ANN001
    with Ledger(drifted) as led:
        v = run_nightly_challenge(led, context)

    assert v.status == "FAIL"
    assert v.measured_ece is not None and v.measured_ece > v.target_ece
    # The verdict must carry what it measured, not just a label: a reviewer
    # reads the gap, not the word.
    assert f"{v.measured_ece:.2f}" in v.reason or str(round(v.measured_ece, 4)) in v.reason


def test_empty_ledger_is_inconclusive_not_pass(tmp_path: Path, context) -> None:  # noqa: ANN001
    p = tmp_path / "empty.sqlite"
    Ledger(p).close()

    with Ledger(p) as led:
        v = run_nightly_challenge(led, context)

    assert v.status == "INCONCLUSIVE"
    assert v.n_samples == 0


def test_below_min_samples_is_inconclusive(tmp_path: Path, context) -> None:  # noqa: ANN001
    p = _ledger(tmp_path, "thin", n=3, confidence=0.98, correct=True)

    with Ledger(p) as led:
        v = run_nightly_challenge(led, context)

    assert v.status == "INCONCLUSIVE"
    assert v.n_samples == 3
    assert "min_samples" in v.reason or "3" in v.reason


def test_min_samples_is_the_explicit_cold_start_knob(tmp_path: Path, context) -> None:  # noqa: ANN001
    p = _ledger(tmp_path, "thin", n=3, confidence=0.98, correct=True)

    with Ledger(p) as led:
        v = run_nightly_challenge(led, context, min_samples=3)

    assert v.status == "PASS"


# --- what the verdict carries ----------------------------------------------


def test_verdict_reports_the_context_and_target_it_judged_against(
    calibrated: Path, context
) -> None:  # noqa: ANN001
    with Ledger(calibrated) as led:
        v = run_nightly_challenge(led, context)

    assert v.context_name == "regulatory-qa"
    assert v.target_ece == pytest.approx(0.03)
    assert v.method == "confidence"


def test_verdict_includes_the_meta_calibration_surface(calibrated: Path, context) -> None:  # noqa: ANN001
    """The challenge layer's own calibration travels with the deployment's."""
    from lub.challenge import MetaCalibrator

    with Ledger(calibrated) as led:
        mc = MetaCalibrator(ledger=led)
        mc.add_prediction("young", 0.8, horizon_days=90)
        mc.record_outcome("young", held_up=True)
        v = run_nightly_challenge(led, mc_context := context)

    assert mc_context is context
    assert v.pending_claims == 1
    assert v.meta_observations == 0


def test_verdict_is_frozen(calibrated: Path, context) -> None:  # noqa: ANN001
    from dataclasses import FrozenInstanceError

    with Ledger(calibrated) as led:
        v = run_nightly_challenge(led, context)

    with pytest.raises(FrozenInstanceError):
        v.status = "PASS"  # type: ignore[misc]


def test_verdict_serialises_for_transport(calibrated: Path, context) -> None:  # noqa: ANN001
    """The BFF ships this over HTTP; it has to be a plain dict of scalars."""
    import json

    with Ledger(calibrated) as led:
        v = run_nightly_challenge(led, context)

    payload = v.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["status"] == "PASS"
    assert payload["context"] == "regulatory-qa"
