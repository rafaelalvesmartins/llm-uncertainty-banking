# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Opt-in: tiny Anthropic Messages smoke test."""
from __future__ import annotations

from tests.integration.real_backend._helpers import (
    require_env,
    require_sdk,
    skip_unless_opted_in,
)


def test_anthropic_generate_single_message() -> None:
    skip_unless_opted_in()
    require_sdk("anthropic")
    require_env("ANTHROPIC_API_KEY")

    from lub.wrappers.anthropic import AnthropicBackend

    backend = AnthropicBackend(model_id="claude-haiku-4-5-20251001")
    out = backend.generate("Say 'ok'.", n_samples=1, temperature=0.0, max_tokens=16)

    assert len(out) == 1
    gen = out[0]
    assert isinstance(gen.text, str)
    assert gen.text.strip(), "empty completion from Anthropic"
    assert isinstance(gen.finish_reason, str) and gen.finish_reason
