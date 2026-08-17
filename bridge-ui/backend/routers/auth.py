# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Authentication — verifiable identity, additive and gated (v6 Phase 1).

The smallest SAFE first slice toward production: a real EdDSA-signed JWT
(`POST /auth/token`) and a `verify_token` dependency. It is **additive** and
gated by ``BRIDGE_AUTH`` — when off (the default), ``verify_token`` yields no
principal and callers fall back to their current behaviour, so the demo and CI
keep working unchanged. When on, identity is signature-bound: the governance
endpoints derive ``submitted_by``/``reviewer`` from ``token.sub`` instead of
trusting body strings, making the segregation-of-duties check sound.

This is real crypto, not mock auth. What it is NOT (yet): production user store,
password hashing, KMS-held key, multi-tenant scoping — those are later v6 phases.
The signing key is an ephemeral per-process demo key behind a swappable seam; the
demo credentials below are demo-only.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()

_TTL_SECONDS = 3600


def _auth_enabled() -> bool:
    return os.environ.get("BRIDGE_AUTH", "off").lower() in ("on", "1", "true", "required")


# JWT signing key (EdDSA) — ephemeral per process behind a KeyManager seam; v6
# Phase 4 swaps this for a managed/HSM key. Never exported.
_KEY = Ed25519PrivateKey.generate()
_PUB_BYTES = _KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
_PUB_HEX = _PUB_BYTES.hex()

# Demo users — NOT a production identity store (no hashing). v6 Phase 2 replaces this.
_USERS: dict[str, dict[str, Any]] = {
    "ana.analista": {"password": "demo-ana", "roles": ["analyst"]},
    "bruno.validador": {"password": "demo-bruno", "roles": ["validator"]},
    "carla.mrm": {"password": "demo-carla", "roles": ["admin"]},
}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(sub: str, roles: list[str]) -> str:
    header = {"alg": "EdDSA", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": sub, "roles": roles, "iat": now, "exp": now + _TTL_SECONDS}
    signing_input = _b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64url(
        json.dumps(payload, separators=(",", ":")).encode()
    )
    sig = _KEY.sign(signing_input.encode("ascii"))
    return signing_input + "." + _b64url(sig)


def verify_jwt(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        Ed25519PublicKey.from_public_bytes(_PUB_BYTES).verify(_b64url_decode(sig_b64), signing_input)
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001 — any failure is an invalid token
        raise HTTPException(status_code=401, detail="invalid token") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="token expired")
    return payload


class TokenRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/token")
def auth_token(req: TokenRequest) -> dict[str, Any]:
    """Exchange demo credentials for an EdDSA-signed JWT."""
    user = _USERS.get(req.username)
    ok = user is not None and secrets.compare_digest(req.password, str(user["password"]))
    if not ok:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {
        "access_token": issue_token(req.username, list(user["roles"])),
        "token_type": "bearer",
        "expires_in": _TTL_SECONDS,
    }


@router.get("/auth/jwks")
def jwks() -> dict[str, Any]:
    """Public key + auth status, so a verifier can check tokens out of band."""
    return {"alg": "EdDSA", "public_key": _PUB_HEX, "auth_enabled": _auth_enabled()}


def verify_token(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    """Dependency: returns the principal when authenticated, else None.

    When BRIDGE_AUTH is off (default), returns None — callers keep their current
    (demo) behaviour. When on, a valid Bearer token is required.
    """
    if not _auth_enabled():
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return verify_jwt(authorization.split(" ", 1)[1].strip())


__all__ = ["router", "verify_token", "issue_token", "verify_jwt"]
