# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Opt-in: tiny local-HF smoke test.

Uses the smallest HuggingFace model we can get away with (sshleifer's
tiny-gpt2) so the test completes in seconds on CPU. Skips unless the
user opts in AND has transformers+torch available.
"""
from __future__ import annotations

from tests.integration.real_backend._helpers import require_sdk, skip_unless_opted_in


def test_hf_generate_tiny_gpt2() -> None:
    skip_unless_opted_in()
    require_sdk("torch")
    require_sdk("transformers")

    from lub.wrappers.hf import HFBackend

    backend = HFBackend(model_id="sshleifer/tiny-gpt2", device="cpu")
    out = backend.generate("Hello", n_samples=1, temperature=0.0, max_tokens=4)

    assert len(out) == 1
    gen = out[0]
    assert isinstance(gen.text, str)
    # tiny-gpt2 often produces garbage but must produce something.
    assert isinstance(gen.finish_reason, str)
