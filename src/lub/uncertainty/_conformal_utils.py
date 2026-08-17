# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared utilities for conformal-prediction-based estimators.

Extracted from :mod:`lub.uncertainty.conformal` to break the hidden
cross-module dependency where ``adaptive_conformal``, ``conformal_sampling``,
and ``mondrian_conformal`` all imported a private function from ``conformal``.
"""

from __future__ import annotations

from lub.protocols import BackendProto


def token_logprob_nonconformity(
    backend: BackendProto,
    prompt: str,
    completion: str,
) -> float:
    """Nonconformity = negative mean token log-probability of ``completion``.

    Lower nonconformity means the model assigns more probability mass to
    the gold completion, i.e. the example is "more conforming".

    Used by:
        - :class:`~lub.uncertainty.conformal.ConformalEstimator`
        - :class:`~lub.uncertainty.adaptive_conformal.AdaptiveConformalEstimator`
        - :class:`~lub.uncertainty.conformal_sampling.ConformalSamplingEstimator`
        - :class:`~lub.uncertainty.mondrian_conformal.MondrianConformalEstimator`
    """
    tlp = backend.logprobs(prompt, completion)
    if not tlp.logprobs:
        return float("inf")
    mean_logprob = sum(tlp.logprobs) / len(tlp.logprobs)
    return -float(mean_logprob)


__all__ = ["token_logprob_nonconformity"]
