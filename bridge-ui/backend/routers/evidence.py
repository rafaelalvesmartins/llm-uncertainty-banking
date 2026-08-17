# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Model-risk evidence package — the regulator-filable artifact (P2).

SR 11-7 "effective challenge" expects auditable, reproducible per-model evidence
a second-line validator can place in a model-risk file. This endpoint assembles
ONE package from the live demonstrator state — the Model Card (inventory), the
real calibration (ECE/Brier/AUROC + reliability), the multi-framework regulatory
crosswalk, and the SR 11-7 pillar mapping — and stamps it with a deterministic
content hash (sha256) and a generation timestamp.

This is the lub differentiator made tangible: guardrail / cache / observability
tools gate, cache, and monitor; none of them emit a supervisory **evidence
record**. The package is now **signed**: an Ed25519 signature over
(content_sha256 | generated_at) makes it dated and tamper-evident — a verifier
re-checks it with the included public key, and flipping any byte fails. The key
is an ephemeral demo key; production would use a managed/HSM key + an RFC 3161
timestamp from an external TSA. /evidence/verify performs the verification.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()

# Ed25519 signing key — ephemeral, generated once per process. Real, verifiable
# asymmetric signature (non-repudiable for whoever holds the private key); in
# production this would be a managed/HSM key + an RFC 3161 timestamp from an
# external TSA. The public key travels in the package so anyone can verify.
_PRIVATE_KEY = Ed25519PrivateKey.generate()
_PUBLIC_KEY_BYTES = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)
_PUBLIC_KEY_HEX = _PUBLIC_KEY_BYTES.hex()
_KEY_ID = hashlib.sha256(_PUBLIC_KEY_BYTES).hexdigest()[:16]


def _sign(payload: str) -> dict[str, Any]:
    signature = _PRIVATE_KEY.sign(payload.encode("utf-8"))
    return {
        "algorithm": "Ed25519",
        "key_id": _KEY_ID,
        "public_key": _PUBLIC_KEY_HEX,
        "signed_payload": payload,
        "signature": signature.hex(),
        "note": (
            "Ed25519 signature over (content_sha256 | generated_at) — binds content and "
            "time. Ephemeral demo key (per process); production would use a managed/HSM key "
            "+ an RFC 3161 timestamp from an external TSA. Verifiable with the public key."
        ),
    }


def _verify(payload: str, signature_hex: str, public_key_hex: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(bytes.fromhex(signature_hex), payload.encode("utf-8"))
        return True
    except (InvalidSignature, ValueError):
        return False


def _server() -> ModuleType:
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


def _routers():
    try:
        from backend.routers import calibration, compliance, model_card
    except ImportError:
        from routers import calibration, compliance, model_card  # type: ignore[no-redef]
    return model_card, calibration, compliance


def build_evidence_package() -> dict[str, Any]:
    """Assemble the model-risk evidence package from live demonstrator state."""
    s = _server()
    model_card, calibration, compliance = _routers()

    # The auditable content (everything except the envelope/timestamp). Hashing
    # this — not the timestamp — keeps the digest reproducible for a given state.
    content: dict[str, Any] = {
        "model_card": model_card._build_model_card(s),
        "calibration": calibration._build_calibration(s),
        "regulatory_coverage": compliance.compliance_frameworks(),
        "sr_11_7": s._SR_11_7_PAYLOAD,
        # Self-anchor the filable artifact to the tamper-evident audit chain it
        # summarizes — the two flagship trust primitives now cross-reference.
        "audit_anchor": {
            "chain_head_seq": getattr(s, "_AUDIT_SEQ", 0),
            "chain_head_hash": getattr(s, "_AUDIT_LAST_HASH", None),
            "note": "Re-verify the chain up to this head at /audit/verify.",
        },
    }
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    signature = _sign(f"{digest}|{generated_at}")

    return {
        "title": "Model-Risk Evidence Package — Bridge Banking AI",
        "owner": "Rafael Martins Alves",
        "generated_at": generated_at,
        "content_sha256": digest,
        "signature": signature,
        "frameworks_covered": content["regulatory_coverage"].get("n_frameworks"),
        "controls_covered": content["regulatory_coverage"].get("n_controls_total"),
        "note": (
            "Canonical package with a deterministic sha256 hash (reproducible for a given "
            "state) AND an Ed25519 signature over (hash | timestamp) — dated, tamper-evident "
            "evidence, verifiable with the included public key, and anchored to the audit "
            "chain head (audit_anchor). Ephemeral demo key; production would use an HSM + "
            "RFC 3161 TSA. Fake backend (no real data)."
        ),
        "content": content,
    }


class VerifyRequest(BaseModel):
    content_sha256: str
    generated_at: str
    signature: str
    public_key: str


@router.get("/evidence/package")
def evidence_package() -> dict[str, Any]:
    """Return the assembled model-risk evidence package (Model Card + calibration
    + regulatory crosswalk + SR 11-7), hashed, timestamped and Ed25519-signed."""
    return build_evidence_package()


@router.get("/evidence/oscal")
def evidence_oscal() -> Response:
    """Emit the latest real-model benchmark run as an OSCAL 1.1.2 component-definition —
    the machine-readable evidence a GRC tool (e.g. OSCAL Trestle) ingests, which the
    console otherwise never produced. Skips Dummy/Fake runs so a sanity-test null is
    never dressed as evidence; 404 if no real run exists yet."""
    import os

    from lub.reports.oscal import render_oscal_json
    from lub.types import BenchmarkResult

    results_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "benchmarks", "results")
    )
    try:
        files = [os.path.join(results_dir, f) for f in os.listdir(results_dir) if f.endswith(".json")]
    except OSError:
        files = []
    record: BenchmarkResult | None = None
    for path in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        backend = str(payload.get("backend", "")).lower()
        if "dummy" in backend or "fake" in backend:
            continue
        try:
            record = BenchmarkResult.model_validate(payload)
        except ValidationError:
            continue
        break
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No real-model benchmark result found — run scripts/run_real_benchmark.py first.",
        )
    oscal = render_oscal_json(record, title="lub — model-risk evidence (OSCAL 1.1.2)")
    return Response(content=oscal, media_type="application/json")


@router.post("/evidence/verify")
def evidence_verify(req: VerifyRequest) -> dict[str, Any]:
    """Verify an evidence package's Ed25519 signature over (hash | timestamp).
    Flipping any byte of the hash or timestamp makes this return valid=false."""
    payload = f"{req.content_sha256}|{req.generated_at}"
    valid = _verify(payload, req.signature, req.public_key)
    return {
        "valid": valid,
        "algorithm": "Ed25519",
        "key_id": _KEY_ID,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


__all__ = ["router"]
