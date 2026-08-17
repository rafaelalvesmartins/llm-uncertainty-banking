# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""vLLM backend for high-throughput local inference.

vLLM (Kwon et al. 2023) uses PagedAttention to reach much higher GPU
throughput than vanilla transformers on batched generation. For the
benchmark runner this matters: a 1000-example FinQA sweep that takes an
hour on :class:`HFBackend` can finish in minutes here.

The backend is inference-only. Embeddings raise
:class:`NotImplementedError` — vLLM does not expose a sentence-embedding
API, and users who need embeddings should stay on :class:`HFBackend`.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import structlog

from lub.types import Generation, TokenLogProbs
from lub.wrappers.base import BackendCapability, ModelBackend

_LOG = structlog.get_logger("lub.wrappers.vllm")


class VLLMBackend(ModelBackend):
    """High-throughput local backend built on vLLM."""

    REGISTRY_KEY = "vllm"
    CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS

    def __init__(
        self,
        model_id: str,
        tensor_parallel_size: int = 1,
        dtype: str = "auto",
        gpu_memory_utilization: float = 0.9,
    ) -> None:
        super().__init__(model_id=model_id)
        self.tensor_parallel_size = tensor_parallel_size
        self.dtype = dtype
        self.gpu_memory_utilization = gpu_memory_utilization
        self._engine: Any = None
        self._lock = threading.Lock()

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                from vllm import LLM
            except ImportError as exc:
                raise ImportError(
                    "vLLM backend requires `vllm`. Install with: "
                    "pip install llm-uncertainty-banking[vllm]"
                ) from exc
            self._engine = LLM(
                model=self.model_id,
                tensor_parallel_size=self.tensor_parallel_size,
                dtype=self.dtype,
                gpu_memory_utilization=self.gpu_memory_utilization,
            )
            return self._engine

    def _sampling_params(
        self,
        n_samples: int,
        temperature: float,
        max_tokens: int,
        *,
        logprobs: int = 5,
    ) -> Any:
        from vllm import SamplingParams

        return SamplingParams(
            n=n_samples,
            temperature=temperature,
            max_tokens=max_tokens,
            logprobs=logprobs,
        )

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Sample ``n_samples`` completions for ``prompt`` via the vLLM engine."""
        engine = self._ensure_engine()
        params = self._sampling_params(n_samples, temperature, max_tokens)
        outputs = engine.generate([prompt], params)
        if not outputs:
            return []

        completions = outputs[0].outputs
        results: list[Generation] = []
        for completion in completions:
            token_logprobs: list[float] = []
            raw_lp = getattr(completion, "logprobs", None) or []
            for step in raw_lp:
                if not step:
                    continue
                # ``step`` is a dict[token_id -> Logprob]; the chosen token
                # is the one with the highest logprob at this step.
                try:
                    best = max(step.values(), key=lambda lp: float(lp.logprob))
                    token_logprobs.append(float(best.logprob))
                except (AttributeError, ValueError):  # pragma: no cover
                    continue
            results.append(
                Generation(
                    text=completion.text,
                    logprobs=token_logprobs or None,
                    finish_reason=getattr(completion, "finish_reason", None),
                )
            )
        return results

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Score ``completion`` under ``prompt`` and return per-token logprobs."""
        engine = self._ensure_engine()
        from vllm import SamplingParams

        params = SamplingParams(max_tokens=0, temperature=0.0, prompt_logprobs=1)
        outputs = engine.generate([prompt + completion], params)
        if not outputs:
            return TokenLogProbs(tokens=[], logprobs=[])

        result = outputs[0]
        raw = getattr(result, "prompt_logprobs", None) or []
        tok = engine.get_tokenizer()
        prompt_len = len(tok.encode(prompt, add_special_tokens=False))

        tokens: list[str] = []
        logprobs: list[float] = []
        for step in raw[prompt_len:]:
            if not step:
                continue
            token_id, lp_obj = next(iter(step.items()))
            tokens.append(str(getattr(lp_obj, "decoded_token", token_id)))
            logprobs.append(float(lp_obj.logprob))
        return TokenLogProbs(tokens=tokens, logprobs=logprobs)

    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Raise :class:`NotImplementedError` — vLLM does not support embeddings."""
        raise NotImplementedError(
            "VLLMBackend does not support embeddings — use HFBackend for embeddings."
        )


__all__ = ["VLLMBackend"]
