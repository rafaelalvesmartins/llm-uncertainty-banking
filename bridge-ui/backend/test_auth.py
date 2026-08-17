# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Authentication (v6 Phase 1) — EdDSA JWT + the governance identity wiring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

try:
    from backend.routers import auth as a  # noqa: E402
    from backend.routers import governance_changes as gc  # noqa: E402
except ImportError:
    from routers import auth as a  # type: ignore[no-redef]  # noqa: E402
    from routers import governance_changes as gc  # type: ignore[no-redef]  # noqa: E402


def test_token_issue_and_verify_roundtrip() -> None:
    p = a.verify_jwt(a.issue_token("ana.analista", ["analyst"]))
    assert p["sub"] == "ana.analista"
    assert "analyst" in p["roles"]


def test_auth_token_rejects_bad_password() -> None:
    with pytest.raises(HTTPException) as exc:
        a.auth_token(a.TokenRequest(username="ana.analista", password="wrong"))
    assert exc.value.status_code == 401


def test_expired_token_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(a, "_TTL_SECONDS", -10)
    tok = a.issue_token("ana.analista", ["analyst"])
    with pytest.raises(HTTPException) as exc:
        a.verify_jwt(tok)
    assert exc.value.status_code == 401


def test_tampered_token_is_rejected() -> None:
    h, p, s = a.issue_token("ana.analista", ["analyst"]).split(".")
    tampered = f"{h}.{p[:-1]}{'A' if p[-1] != 'A' else 'B'}.{s}"
    with pytest.raises(HTTPException):
        a.verify_jwt(tampered)


def test_verify_token_off_yields_no_principal(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_AUTH", "off")
    assert a.verify_token(authorization=None) is None


def test_verify_token_on_requires_a_valid_bearer(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_AUTH", "on")
    with pytest.raises(HTTPException) as exc:
        a.verify_token(authorization=None)
    assert exc.value.status_code == 401
    tok = a.issue_token("bruno.validador", ["validator"])
    principal = a.verify_token(authorization=f"Bearer {tok}")
    assert principal is not None and principal["sub"] == "bruno.validador"


def test_authenticated_identity_overrides_spoofed_body(monkeypatch) -> None:
    # closes the SoD gap: a verified token subject wins over body strings
    monkeypatch.setattr(gc, "_DB_PATH", ":memory:")
    monkeypatch.setattr(gc, "_DB", None)
    # use a validator as submitter so RBAC passes and we isolate the SoD check
    r = gc.submit_endpoint(
        gc.SubmitRequest(kind="agent", summary="x", submitted_by="SPOOFED"),
        principal={"sub": "bruno.validador", "roles": ["validator"]},
    )
    cid = r["id"]
    assert gc.list_changes()["changes"][0]["submitted_by"] == "bruno.validador"  # not "SPOOFED"
    # same verified subject cannot self-approve (SoD), even with approve rights
    with pytest.raises(HTTPException) as exc:
        gc.decision_endpoint(
            cid,
            gc.DecisionRequest(decision="approve", reviewer="SPOOFED"),
            principal={"sub": "bruno.validador", "roles": ["validator"]},
        )
    assert exc.value.status_code == 400
    # a different verified reviewer (admin) approves
    out = gc.decision_endpoint(
        cid,
        gc.DecisionRequest(decision="approve", reviewer="SPOOFED"),
        principal={"sub": "carla.mrm", "roles": ["admin"]},
    )
    assert out["status"] == "approved"
    assert gc.list_changes()["changes"][0]["reviewer"] == "carla.mrm"


def test_rbac_only_validator_or_admin_can_decide(monkeypatch) -> None:
    monkeypatch.setattr(gc, "_DB_PATH", ":memory:")
    monkeypatch.setattr(gc, "_DB", None)
    cid = gc.submit_endpoint(
        gc.SubmitRequest(kind="agent", summary="x", submitted_by="x"),
        principal={"sub": "ana.analista", "roles": ["analyst"]},
    )["id"]
    # an analyst cannot decide (RBAC), even a different one
    with pytest.raises(HTTPException) as exc:
        gc.decision_endpoint(
            cid,
            gc.DecisionRequest(decision="approve", reviewer="x"),
            principal={"sub": "ze.analista", "roles": ["analyst"]},
        )
    assert exc.value.status_code == 403
    # a validator can
    out = gc.decision_endpoint(
        cid,
        gc.DecisionRequest(decision="approve", reviewer="x"),
        principal={"sub": "bruno.validador", "roles": ["validator"]},
    )
    assert out["status"] == "approved"
