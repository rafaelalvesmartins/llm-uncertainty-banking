# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Opt-in: in-process vLLM smoke test.

VLLMBackend spawns an in-process vLLM engine (not a remote client).
Running this test requires LUB_REAL_BACKEND_TESTS=1, the `vllm`
package installed, and LUB_VLLM_MODEL set to a reachable model id.
Skipped gracefully otherwise.
"""
from __future__ import annotations

import os

from tests.integration.real_backend._helpers import (
    require_env,
    require_sdk,
    skip_unless_opted_in,
)


def test_vllm_engine_generates_in_process() -> None:
    skip_unless_opted_in()
    require_sdk("vllm")
    require_env("LUB_VLLM_MODEL")

    from lub.wrappers.vllm import VLLMBackend

    backend = VLLMBackend(model_id=os.environ["LUB_VLLM_MODEL"])
    out = backend.generate("Say 'ok'.", n_samples=1, temperature=0.0, max_tokens=4)

    assert len(out) == 1
    gen = out[0]
    assert isinstance(gen.text, str)
    assert isinstance(gen.finish_reason, str) and gen.finish_reason
