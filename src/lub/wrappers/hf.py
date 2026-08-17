# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""HuggingFace ``transformers`` backend.

Loads an ``AutoModelForCausalLM`` + ``AutoTokenizer`` pair lazily on first
use so that importing this module is cheap and side-effect free. The loaded
model is cached on the instance and protected by a lock so that the backend
is safe to share across threads (e.g. a pipeline running several estimators
in parallel on the same model).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

from lub.types import Generation, TokenLogProbs
from lub.wrappers.base import BackendCapability, ModelBackend

_LOG = structlog.get_logger("lub.wrappers.hf")

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from transformers import PreTrainedModel, PreTrainedTokenizerBase


_MISSING_DEPS_MSG = (
    "HFBackend requires 'transformers' and 'torch'. Install with: pip install transformers torch"
)


class HFBackend(ModelBackend):
    """Local HuggingFace causal-LM backend."""

    REGISTRY_KEY = "hf"
    CAPABILITIES = BackendCapability.GENERATE | BackendCapability.LOGPROBS | BackendCapability.EMBED

    def __init__(
        self,
        model_id: str,
        device: str | None = None,
        revision: str | None = None,
    ) -> None:
        """Construct the backend.

        Args:
            model_id: HuggingFace model id (e.g. "meta-llama/Llama-2-7b").
            device: Optional explicit device ("cuda", "cpu"); auto-detected
                when omitted.
            revision: Pin to a specific commit/tag/branch on the Hub.
                **Strongly recommended for production deployments** —
                without a pinned revision, a malicious or accidental
                upstream commit could swap the model under you. Defaults
                to None for backward compat (= HF default branch, latest).
        """
        super().__init__(model_id)
        self._device = device
        self._revision = revision
        self._lock = threading.Lock()
        self._model: PreTrainedModel | None = None
        self._tokenizer: PreTrainedTokenizerBase | None = None

    def _load(self) -> tuple[PreTrainedModel, PreTrainedTokenizerBase, str]:
        with self._lock:
            if self._model is not None and self._tokenizer is not None:
                if self._device is None:  # pragma: no cover
                    raise RuntimeError("HFBackend: model loaded but device not set")
                return self._model, self._tokenizer, self._device
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
            except ImportError as exc:  # pragma: no cover - exercised via integration
                raise ImportError(_MISSING_DEPS_MSG) from exc

            device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
            tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=self._revision)
            if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
                tokenizer.pad_token = tokenizer.eos_token
            model = AutoModelForCausalLM.from_pretrained(self.model_id, revision=self._revision)
            model.to(device)
            model.eval()

            self._model = model
            self._tokenizer = tokenizer
            self._device = device
            return model, tokenizer, device

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Sample ``n_samples`` completions from the local causal LM."""
        if n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {n_samples}")
        import torch

        model, tokenizer, device = self._load()
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        input_len = int(inputs["input_ids"].shape[1])

        gen_kwargs: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "num_return_sequences": n_samples,
            "pad_token_id": tokenizer.pad_token_id,
            "return_dict_in_generate": True,
            "output_scores": True,
        }
        if n_samples > 1 or temperature > 0:
            gen_kwargs["do_sample"] = True
            gen_kwargs["temperature"] = max(temperature, 1e-5)
        else:
            gen_kwargs["do_sample"] = False

        with torch.no_grad():
            output = model.generate(**inputs, **gen_kwargs)

        sequences = output.sequences
        results: list[Generation] = []
        for i in range(n_samples):
            new_tokens = sequences[i, input_len:]
            text = tokenizer.decode(new_tokens, skip_special_tokens=True)
            seq_logprobs: list[float] = []
            if output.scores is not None:
                for step_idx, step_scores in enumerate(output.scores):
                    log_probs = torch.log_softmax(step_scores[i], dim=-1)
                    tok_id = (
                        int(new_tokens[step_idx].item()) if step_idx < new_tokens.shape[0] else None
                    )
                    if tok_id is None:
                        break
                    seq_logprobs.append(float(log_probs[tok_id].item()))
            results.append(Generation(text=text, logprobs=seq_logprobs, finish_reason="stop"))
        return results

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Return per-token log-probabilities of ``completion`` given ``prompt``."""
        import torch

        model, tokenizer, device = self._load()
        prompt_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(device)
        full_ids = tokenizer(prompt + completion, return_tensors="pt").input_ids.to(device)
        completion_start = int(prompt_ids.shape[1])

        with torch.no_grad():
            logits = model(full_ids).logits
        log_probs = torch.log_softmax(logits, dim=-1)

        completion_ids = full_ids[0, completion_start:]
        tokens: list[str] = []
        scores: list[float] = []
        for offset, tok_id in enumerate(completion_ids.tolist()):
            pred_pos = completion_start + offset - 1
            if pred_pos < 0:
                continue
            scores.append(float(log_probs[0, pred_pos, tok_id].item()))
            tokens.append(tokenizer.decode([tok_id]))
        return TokenLogProbs(tokens=tokens, logprobs=scores)

    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Return a mean-pooled last-hidden-state embedding for ``text``."""
        import torch

        model, tokenizer, device = self._load()
        inputs = tokenizer(text, return_tensors="pt", truncation=True).to(device)
        with torch.no_grad():
            outputs = model(**inputs, output_hidden_states=True)
        hidden = outputs.hidden_states[-1][0]
        mask = inputs["attention_mask"][0].unsqueeze(-1).float()
        summed = (hidden * mask).sum(dim=0)
        denom = mask.sum().clamp(min=1.0)
        pooled = (summed / denom).cpu().numpy()
        return np.asarray(pooled, dtype=np.float32)


__all__ = ["HFBackend"]
