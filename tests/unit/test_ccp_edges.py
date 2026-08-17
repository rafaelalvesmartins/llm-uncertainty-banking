# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""CCP edge-case tests covering the 'no claims extracted' and
unparseable-verdict paths."""

from __future__ import annotations

import numpy as np

from lub.types import Generation, TokenLogProbs
from lub.uncertainty.ccp import CCPEstimator
from lub.wrappers.base import ModelBackend


class _ScriptedBackend(ModelBackend):
    """Returns a queue of pre-scripted generations in order of call."""

    def __init__(self, scripts: list[str]) -> None:
        super().__init__(model_id="scripted-0")
        self._scripts = list(scripts)

    def generate(
        self,
        prompt: str,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        if not self._scripts:
            return []
        return [Generation(text=self._scripts.pop(0))]

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        return TokenLogProbs(tokens=[], logprobs=[])

    def embed(self, text: str) -> np.ndarray:
        return np.zeros(4, dtype=np.float64)


def test_ccp_returns_zero_when_decomposition_yields_no_claims() -> None:
    # First call: the answer. Second call: decomposition returns prose
    # with no numbered claims, so _parse_claims() returns [].
    backend = _ScriptedBackend([
        "Basel III raises CET1 to 4.5%.",
        "This is just prose without any numbered claims.",
    ])
    est = CCPEstimator()
    result = est.score(backend, "What is CET1?")

    assert result.confidence == 0.0
    assert result.should_refuse is True
    assert result.raw_scores["n_claims"] == 0.0
    assert result.raw_scores["n_supported"] == 0.0


def test_ccp_scores_all_supported_when_every_claim_passes() -> None:
    # Answer → 3 numbered claims → 3 "Supported" verdicts.
    backend = _ScriptedBackend([
        "Basel III raises CET1 to 4.5%.",
        "1. CET1 is defined by Basel III.\n2. The minimum is 4.5%.\n3. It excludes deferred tax assets.",
        "Supported",
        "Supported",
        "Supported",
    ])
    est = CCPEstimator()
    result = est.score(backend, "What is CET1?")

    assert result.confidence == 1.0
    assert result.raw_scores["n_claims"] == 3.0
    assert result.raw_scores["n_supported"] == 3.0
    assert result.should_refuse is False


def test_ccp_unparseable_verdicts_count_as_unsupported() -> None:
    backend = _ScriptedBackend([
        "Basel III CET1 is 4.5%.",
        "1. CET1 is 4.5%.\n2. It is a regulatory ratio.",
        "mumble mumble mumble",  # no "Supported" match → counts as 0
        "Supported",
    ])
    est = CCPEstimator()
    result = est.score(backend, "q")

    assert result.raw_scores["n_claims"] == 2.0
    assert result.raw_scores["n_supported"] == 1.0
    assert result.confidence == 0.5


def test_ccp_respects_max_claims() -> None:
    backend = _ScriptedBackend([
        "Answer",
        # 5 claims but max_claims=2, so only 2 will be verified.
        "1. A\n2. B\n3. C\n4. D\n5. E",
        "Supported",
        "Supported",
    ])
    est = CCPEstimator(max_claims=2)
    result = est.score(backend, "q")

    assert result.raw_scores["n_claims"] == 2.0
    assert result.raw_scores["n_supported"] == 2.0
