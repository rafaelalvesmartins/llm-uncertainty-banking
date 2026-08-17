# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Model-risk evidence package endpoint (P2).

Asserts the package assembles the four evidence sections and carries a
deterministic content hash (reproducible for a given state) plus a timestamp.

Run from the project root::

    pytest bridge-ui/backend/test_evidence_package.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401

try:
    from backend.routers import evidence as ev  # noqa: E402
except ImportError:
    from routers import evidence as ev  # type: ignore[no-redef]  # noqa: E402


def test_package_assembles_all_evidence_sections() -> None:
    p = ev.evidence_package()
    assert p["owner"]
    assert p["generated_at"]
    for key in ("model_card", "calibration", "regulatory_coverage", "sr_11_7"):
        assert key in p["content"], f"missing evidence section {key}"
    assert p["frameworks_covered"] >= 5
    assert p["controls_covered"] >= 20


def test_content_hash_is_sha256_and_reproducible(monkeypatch) -> None:
    # pin the runtime state so the content (and therefore the hash) is stable.
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.7)
    a = ev.evidence_package()
    b = ev.evidence_package()
    assert re.fullmatch(r"[0-9a-f]{64}", a["content_sha256"])
    # same state -> same content hash (timestamp differs but isn't hashed)
    assert a["content_sha256"] == b["content_sha256"]


def test_hash_tracks_state_changes(monkeypatch) -> None:
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.7)
    h1 = ev.evidence_package()["content_sha256"]
    # the Model Card carries the runtime guard threshold, so changing it must
    # change the evidence content hash — the package captures the live state.
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.3)
    h2 = ev.evidence_package()["content_sha256"]
    assert h1 != h2


def test_package_is_ed25519_signed_and_verifies() -> None:
    p = ev.evidence_package()
    sig = p["signature"]
    assert sig["algorithm"] == "Ed25519"
    assert re.fullmatch(r"[0-9a-f]+", sig["signature"])
    assert sig["signed_payload"] == f"{p['content_sha256']}|{p['generated_at']}"
    out = ev.evidence_verify(
        ev.VerifyRequest(
            content_sha256=p["content_sha256"],
            generated_at=p["generated_at"],
            signature=sig["signature"],
            public_key=sig["public_key"],
        )
    )
    assert out["valid"] is True


def test_tampered_evidence_fails_verification() -> None:
    p = ev.evidence_package()
    sig = p["signature"]
    # flip one hex char of the content hash — verification must fail
    bad_hash = ("0" if p["content_sha256"][0] != "0" else "1") + p["content_sha256"][1:]
    out = ev.evidence_verify(
        ev.VerifyRequest(
            content_sha256=bad_hash,
            generated_at=p["generated_at"],
            signature=sig["signature"],
            public_key=sig["public_key"],
        )
    )
    assert out["valid"] is False
    # and a tampered timestamp also fails
    out2 = ev.evidence_verify(
        ev.VerifyRequest(
            content_sha256=p["content_sha256"],
            generated_at="2000-01-01T00:00:00+00:00",
            signature=sig["signature"],
            public_key=sig["public_key"],
        )
    )
    assert out2["valid"] is False
