# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""L1 model backend wrappers.

``VLLMBackend`` is deliberately not imported at package level — it pulls
in the ``vllm`` extra, which is GPU-only and not installable on macOS or
Windows-without-CUDA. Reach it via ``from lub.wrappers.vllm import
VLLMBackend`` on hosts where it is available, or let
:class:`lub.pipeline.UncertaintyPipeline` load it lazily through the
backend registry.
"""

from lub.wrappers.anthropic import AnthropicBackend
from lub.wrappers.base import ModelBackend
from lub.wrappers.dummy import DummyBackend
from lub.wrappers.hf import HFBackend
from lub.wrappers.openai import OpenAIBackend

__all__ = [
    "AnthropicBackend",
    "DummyBackend",
    "HFBackend",
    "ModelBackend",
    "OpenAIBackend",
]
