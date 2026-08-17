# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Opt-in: tiny OpenAI Chat Completions smoke test."""
from __future__ import annotations

from tests.integration.real_backend._helpers import (
    require_env,
    require_sdk,
    skip_unless_opted_in,
)


def test_openai_generate_single_token() -> None:
    skip_unless_opted_in()
    require_sdk("openai")
    require_env("OPENAI_API_KEY")

    from lub.wrappers.openai import OpenAIBackend

    backend = OpenAIBackend(model_id="gpt-4o-mini")
    out = backend.generate("Say 'ok'.", n_samples=1, temperature=0.0, max_tokens=4)

    assert len(out) == 1
    gen = out[0]
    assert isinstance(gen.text, str)
    assert gen.text.strip(), "empty completion from OpenAI"
    assert gen.finish_reason in {"stop", "length", "end_turn"}
