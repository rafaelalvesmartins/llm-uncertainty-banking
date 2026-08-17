# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Claim-level uncertainty scoring.

Decomposes an LLM answer into individual *claims* (numerical assertions,
factual statements), scores each claim independently via a base
estimator, and aggregates per-claim confidences into a single overall
score. This is the architecture pattern described in Fadeeva et al. 2024
(TACL), adapted for financial QA where each numerical assertion in a
regulatory answer carries its own risk.

Banking value: an auditor reviewing a model-risk report wants to know
which specific number in "The CET1 ratio is 4.5% and the LCR is 100%"
is unreliable — not just that the answer overall is 60% confident.
Claim-level scoring provides that granularity and maps directly to
NIST AI RMF MEASURE 2.7 (per-assertion auditability).

Reference:
    Fadeeva, E., Vashurin, R., Tsvigun, A., et al. (2024).
    *Fact-Checking the Output of Large Language Models via Token-Level
    Uncertainty Quantification.* TACL.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from lub.protocols import BackendProto
from lub.types import UncertaintyResult
from lub.uncertainty.base import Estimator

_NUMERIC_CLAIM_RE = re.compile(
    # \b prevents "CET1" -> "1" and "Basel III 4" -> "4" in identifier-like
    # tokens; we want only standalone numeric claims.
    r"(?:[\$€£¥]?\s*)\b(\d[\d,]*\.?\d*)\s*(%|bps|basis points|percent|pp)?"
    r"|\b(\d[\d,]*\.?\d*)\s*/\s*(\d[\d,]*\.?\d*)",
    re.IGNORECASE,
)


def extract_numeric_claims(text: str) -> list[str]:
    """Extract numeric claims from financial text via regex.

    Returns substrings like ``"4.5%"``, ``"100 basis points"``,
    ``"$1,200"``. Designed for banking QA — not general NER.
    """
    claims: list[str] = []
    for match in _NUMERIC_CLAIM_RE.finditer(text):
        claim = match.group(0).strip()
        if claim:
            claims.append(claim)
    return claims


ClaimDecomposeFn = Callable[[str], list[str]]
"""Signature for a claim-extraction function.

Accepts the answer text, returns a list of atomic claim strings.
Default is :func:`extract_numeric_claims`; callers can supply a
custom function (e.g., NLI-based sentence decomposer) without
changing the estimator class.
"""

_AGGREGATIONS = ("min", "mean", "max")


class ClaimLevelEstimator(Estimator):
    """Per-claim uncertainty scoring (Fadeeva et al. 2024 architecture).

    Three-stage pipeline following the UQLM taxonomy (Bouchard et al.
    2026, arXiv:2602.17431):

    1. **Decomposition** — extract atomic claims from the answer via
       ``decompose_fn`` (default: regex numeric extraction). Pluggable
       so callers can supply NLI-based sentence decomposers.
    2. **Scoring** — score each claim independently by re-prompting the
       ``base_estimator``.
    3. **Aggregation** — combine per-claim confidences via ``min``
       (conservative, default), ``mean``, or ``max``.
    """

    REGISTRY_KEY = "claim_level"

    def __init__(
        self,
        base_estimator: Estimator,
        aggregation: str = "min",
        refusal_threshold: float = 0.5,
        max_tokens: int = 256,
        decompose_fn: ClaimDecomposeFn | None = None,
    ) -> None:
        if aggregation not in _AGGREGATIONS:
            raise ValueError(f"aggregation must be one of {_AGGREGATIONS}, got {aggregation!r}")
        self.base_estimator = base_estimator
        self.aggregation = aggregation
        self.refusal_threshold = self._validate_threshold(refusal_threshold)
        self.max_tokens = max_tokens
        self.decompose_fn: ClaimDecomposeFn = decompose_fn or extract_numeric_claims

    def score(
        self,
        backend: BackendProto,
        prompt: str,
        **kwargs: Any,
    ) -> UncertaintyResult:
        """Compute uncertainty score for the given prompt and answer."""
        max_tokens = int(kwargs.get("max_tokens", self.max_tokens))
        generations = self._require_generations(
            backend.generate(
                prompt,
                n_samples=1,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        answer = generations[0].text

        claims = self.decompose_fn(answer)
        if not claims:
            result = self.base_estimator.score(backend, prompt, **kwargs)
            # Return a NEW UncertaintyResult rather than mutating the
            # base estimator's dict - result.raw_scores is shared state
            # by reference and the base estimator may reuse the object.
            return result.with_raw_scores({**result.raw_scores, "claim_count": 0.0})

        claim_confs: list[float] = []
        claim_details: list[dict[str, Any]] = []
        for claim_text in claims:
            verification_prompt = (
                f"Based on the following context, is this claim accurate?\n\n"
                f"Context: {answer}\n"
                f"Claim: {claim_text}\n\n"
                f"Answer True or False."
            )
            claim_result = self.base_estimator.score(
                backend,
                verification_prompt,
                **kwargs,
            )
            claim_confs.append(claim_result.confidence)
            claim_details.append(
                {
                    "claim": claim_text,
                    "confidence": claim_result.confidence,
                    "should_refuse": claim_result.should_refuse,
                }
            )

        if self.aggregation == "min":
            confidence = min(claim_confs)
        elif self.aggregation == "max":
            confidence = max(claim_confs)
        else:
            confidence = sum(claim_confs) / len(claim_confs)

        confidence = max(0.0, min(1.0, confidence))

        return UncertaintyResult(
            answer=answer,
            confidence=confidence,
            raw_scores={
                "claim_count": float(len(claims)),
                "min_claim_confidence": float(min(claim_confs)),
                "mean_claim_confidence": float(sum(claim_confs) / len(claim_confs)),
            },
            diagnostics={"claims": claim_details},
            samples=[answer],
            should_refuse=confidence < self.refusal_threshold,
        )


__all__ = ["ClaimLevelEstimator", "extract_numeric_claims"]
