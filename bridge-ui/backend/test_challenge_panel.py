# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Continuous effective challenge, surfaced in the console.

The library gained a scheduled CEC command; until now nothing in the product
showed it. This endpoint runs the *same* verdict rule
(``lub.challenge.nightly.run_nightly_challenge``) over the console's own
labelled intent samples, so the governance screen reports a real measurement
of this deployment rather than a number typed into a slide.

Also covers the air-gapped perimeter surfacing on /health: the profile is
enforced in the library, and an operator should be able to see which side of
the perimeter the console is running on.

Run from the project root::

    pytest bridge-ui/backend/test_challenge_panel.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

client = TestClient(server.app)


# --- the verdict ------------------------------------------------------------


def test_endpoint_returns_a_tri_state_verdict() -> None:
    r = client.get("/challenge/nightly")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"PASS", "FAIL", "INCONCLUSIVE"}


def test_verdict_is_measured_over_the_consoles_own_labelled_samples() -> None:
    """Not a canned number: n_samples must match the live catalog."""
    expected = len(server._intent_calibration_samples())

    body = client.get("/challenge/nightly").json()

    assert expected > 0
    assert body["n_samples"] == expected


def test_verdict_carries_the_gap_not_just_the_label() -> None:
    body = client.get("/challenge/nightly").json()

    assert body["target_ece"] == pytest.approx(0.03)
    assert body["measured_ece"] is not None
    assert body["reason"]


def test_default_context_is_the_strictest_one() -> None:
    """Defaulting to the loosest target would be grading on a curve."""
    body = client.get("/challenge/nightly").json()

    assert body["context"] == "regulatory-qa"


def test_context_is_selectable_and_changes_the_target() -> None:
    strict = client.get("/challenge/nightly").json()
    looser = client.get("/challenge/nightly", params={"context": "fraud-alerts"}).json()

    assert looser["context"] == "fraud-alerts"
    assert looser["target_ece"] > strict["target_ece"]
    # Same evidence, judged against a different bar.
    assert looser["n_samples"] == strict["n_samples"]


def test_unknown_context_is_a_client_error() -> None:
    r = client.get("/challenge/nightly", params={"context": "no-such-context"})

    assert r.status_code == 400


def test_meta_calibration_surface_is_present() -> None:
    body = client.get("/challenge/nightly").json()

    for key in ("meta_ece", "meta_observations", "pending_claims"):
        assert key in body


# --- the perimeter ----------------------------------------------------------


def test_health_reports_the_deployment_perimeter() -> None:
    body = client.get("/health").json()

    assert "local_only" in body
    assert isinstance(body["local_only"], bool)


def test_health_perimeter_follows_the_library_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The badge must reflect the enforced profile, not a hardcoded claim."""
    from lub.config import LubConfig

    monkeypatch.setattr(
        "routers.platform._local_only_enabled"
        if "routers.platform" in sys.modules
        else "backend.routers.platform._local_only_enabled",
        lambda: LubConfig(local_only=True).local_only,
    )

    body = client.get("/health").json()

    assert body["local_only"] is True
