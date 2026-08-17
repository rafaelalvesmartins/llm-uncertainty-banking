#!/usr/bin/env python3
"""Verify a downloaded Bridge evidence package OFFLINE — no server (planning/39 #8).

The evidence package (GET /evidence/package, "Export package") carries its own
content, a sha256 over the canonical content, an Ed25519 signature over
(hash | timestamp), and the public key. This script re-checks BOTH locally, so an
auditor can verify the artifact air-gapped:

  1. recompute sha256(canonical(content))  → must equal content_sha256
  2. verify the Ed25519 signature over "<content_sha256>|<generated_at>"

Flipping any byte of the content fails (1); flipping the hash/timestamp fails (2).

    python bridge-ui/scripts/verify_evidence.py path/to/evidence-package.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _canonical(content: dict[str, Any]) -> str:
    # Must match backend build_evidence_package() exactly.
    return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package", help="path to a downloaded evidence package .json")
    args = ap.parse_args()

    with open(args.package, encoding="utf-8") as fh:
        pkg = json.load(fh)

    stated_hash = str(pkg["content_sha256"])
    recomputed = hashlib.sha256(_canonical(pkg["content"]).encode("utf-8")).hexdigest()
    hash_ok = recomputed == stated_hash

    sig = pkg["signature"]
    payload = f"{stated_hash}|{pkg['generated_at']}"
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(sig["public_key"])).verify(
            bytes.fromhex(sig["signature"]), payload.encode("utf-8")
        )
        sig_ok = True
    except (InvalidSignature, ValueError):
        sig_ok = False

    print(f"content hash : {'OK' if hash_ok else 'MISMATCH'} ({recomputed[:16]}… vs {stated_hash[:16]}…)")
    print(f"signature    : {'VALID' if sig_ok else 'INVALID'} (Ed25519 over hash|timestamp)")
    ok = hash_ok and sig_ok
    print(f"=> {'VERIFIED — untampered' if ok else 'FAILED — do not trust this package'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
