# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Claim-Conditioned Probability (CCP) uncertainty estimator.

Decomposes an LLM answer into atomic claims and evaluates each claim's
factual plausibility via a second-pass LLM call. Confidence is the
fraction of claims the model judges as "supported." This is the only
estimator in LUB that operates at the *fact level* rather than the
*answer level*, making it especially relevant for banking tasks where
a single wrong number in an otherwise correct narrative is a material
error (e.g. misquoting a regulatory ratio, a wrong date in a
compliance memo).

The estimator is fully blackbox — no logprobs, no embeddings — so it
works against hosted APIs (OpenAI, Anthropic) where whitebox access is
unavailable.

Reference:
    Fadeeva, E., Rubashevskii, A., Shelmanov, A., et al. (2024).
    *Fact-Checking the Output of Large Language Models via Token-Level
    Uncertainty Quantification.* ACL 2024 Findings. arXiv:2403.04696.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_LOG = structlog.get_logger("lub.uncertainty.ccp")

_DECOMPOSE_TEMPLATE = (
    "Break the following text into a numbered list of independent "
    "factual claims. Each claim should be a single, verifiable "
    "statement. Return ONLY the numbered list, nothing else.\n\n"
    "Text: {answer}\n\n"
    "Claims:"
)

_VERIFY_TEMPLATE = (
    "Question: {question}\n"
    "Claim: {claim}\n\n"
    "Based on the question context, is the above claim factually "
    "correct and supported? Answer with exactly one word: "
    "Supported or Unsupported."
)

_CLAIM_RE = re.compile(r"^\s*\d+[.)]\s*(.+)", re.MULTILINE)
_SUPPORTED_RE = re.compile(r"\bsupported\b", re.IGNORECASE)


def _parse_claims(text: str) -> list[str]:
    claims = _CLAIM_RE.findall(text)
    return [c.strip() for c in claims if c.strip()]


class CCPEstimator(Estimator):
    """Fadeeva et al. 2024 claim-conditioned probability estimator."""

    REGISTRY_KEY = "ccp"

    def __init__(
        self,
        max_claims: int = 10,
        refusal_threshold: float = 0.5,
    ) -> None:
        if max_claims < 1:
            raise ValueError(f"max_claims must be >= 1, got {max_claims}")
        self.max_claims = max_claims
        self.refusal_threshold = self._validate_threshold(refusal_threshold)

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        max_tokens = int(kwargs.get("max_tokens", 256))

        answer_gens = backend.generate(prompt, n_samples=1, temperature=0.0, max_tokens=max_tokens)
        if not answer_gens:
            raise RuntimeError("backend.generate returned no generations")
        answer = answer_gens[0].text.strip()

        decompose_prompt = _DECOMPOSE_TEMPLATE.format(answer=answer)
        decompose_gens = backend.generate(
            decompose_prompt, n_samples=1, temperature=0.0, max_tokens=512
        )
        claims_text = decompose_gens[0].text if decompose_gens else ""
        claims = _parse_claims(claims_text)[: self.max_claims]

        if not claims:
            return UncertaintyResult(
                answer=answer,
                confidence=0.0,
                raw_scores={
                    "n_claims": 0.0,
                    "n_supported": 0.0,
                    "claim_support_rate": 0.0,
                },
                samples=[answer],
                should_refuse=True,
            )

        n_supported = 0
        for claim in claims:
            verify_prompt = _VERIFY_TEMPLATE.format(question=prompt, claim=claim)
            verify_gens = backend.generate(
                verify_prompt, n_samples=1, temperature=0.0, max_tokens=8
            )
            verdict = verify_gens[0].text if verify_gens else ""
            if _SUPPORTED_RE.search(verdict):
                n_supported += 1

        confidence = n_supported / len(claims)
        raw_scores: dict[str, float] = {
            "n_claims": float(len(claims)),
            "n_supported": float(n_supported),
            "claim_support_rate": confidence,
        }
        return UncertaintyResult(
            answer=answer,
            confidence=max(0.0, min(1.0, confidence)),
            raw_scores=raw_scores,
            samples=[answer],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["CCPEstimator"]
