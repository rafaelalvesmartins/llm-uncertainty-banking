# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Structural type protocols for decoupling implementation from interface.

Allows estimators and other components to depend on behavioral contracts
(Protocols) rather than concrete classes, enabling easier testing with mocks
and cleaner architectural boundaries.

The module imports only from :mod:`lub.types`, :mod:`numpy`, and stdlib to
avoid circular dependencies — protocols serve as foundational interfaces
that both high and low layers can depend on.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

from lub.types import Generation, TokenLogProbs, UncertaintyResult


@runtime_checkable
class BackendProto(Protocol):
    """Structural contract for a model backend.

    Anything exposing these methods can be used as a backend. Estimators
    depend on this protocol rather than the concrete :class:`~lub.wrappers.base.ModelBackend`
    class, enabling test mocks and cleaner decoupling.

    The three methods split into two families:

    - **Generation** (generate): Required. Every backend must generate text.
    - **Whitebox extensions** (logprobs, embed): Optional. Backends raise
      :class:`NotImplementedError` if unsupported; estimators catch that
      exception and fall back to a blackbox path where possible.
    """

    def generate(
        self,
        prompt: str,
        *,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        """Return ``n_samples`` completions for ``prompt``.

        Parameters
        ----------
        prompt : str
            The input text.
        n_samples : int, optional
            Number of generations to produce (default 1).
        temperature : float, optional
            Sampling temperature (default 0.7). Must be ``>= 0``; ``0.0``
            requests greedy decoding (used by 15+ estimators that score
            single-sample completions, e.g. ``perplexity``, ``ccp``,
            ``conformal``).
        max_tokens : int, optional
            Maximum tokens per generation (default 256).

        Returns
        -------
        list[Generation]
            List of ``n_samples`` completed generations.

        Raises
        ------
        ValueError
            If input validation fails.
        """
        ...  # pragma: no cover

    def logprobs(self, prompt: str, completion: str) -> TokenLogProbs:
        """Return token-level log-probabilities of ``completion`` given ``prompt``.

        Whitebox (information-rich) backend interface. Estimators that depend
        on this method should catch :class:`NotImplementedError` and provide
        a fallback.

        Parameters
        ----------
        prompt : str
            The input prompt.
        completion : str
            The completion to score.

        Returns
        -------
        TokenLogProbs
            Tokens and their log-probabilities.

        Raises
        ------
        NotImplementedError
            If the backend does not support log-probabilities (e.g., a blackbox
            API). Callers should catch and fall back to a blackbox path.
        """
        ...  # pragma: no cover

    def embed(self, text: str) -> np.ndarray[Any, Any]:
        """Return a fixed-dimensional dense embedding of ``text``.

        Whitebox (information-rich) backend interface for density-based
        estimators. Estimators that depend on this method should catch
        :class:`NotImplementedError` and provide a fallback.

        Parameters
        ----------
        text : str
            Text to embed.

        Returns
        -------
        np.ndarray[Any, Any]
            A 1-D dense vector of fixed dimension.

        Raises
        ------
        NotImplementedError
            If the backend does not support embeddings. Callers should catch
            and fall back to a blackbox path.
        """
        ...  # pragma: no cover


class WhiteboxBackendProto(BackendProto, Protocol):
    """Backend that exposes the underlying PyTorch model for whitebox-only estimators.

    Estimators like MC dropout and LM-Polygraph need direct access to
    ``nn.Module`` internals (dropout toggling, hidden states). This
    protocol lets them declare that dependency without hard-coding
    ``isinstance(backend, HFBackend)``.
    """

    model_id: str

    def _load(self) -> tuple[Any, Any, Any]:
        """Return ``(model, tokenizer, config)`` for the underlying PyTorch model.

        The leading underscore marks this as an implementation hook on the
        Protocol surface (for whitebox estimators that need direct access to
        the underlying ``nn.Module``), not Python's "private" convention; it
        is part of the public Protocol contract and is re-exported in
        ``__all__`` accordingly.

        Raises
        ------
        NotImplementedError
            If the backend does not expose a local PyTorch model.
        """
        ...  # pragma: no cover


@runtime_checkable
class PipelineProto(Protocol):
    """Structural contract for an uncertainty pipeline.

    Anything exposing these methods can be used as a pipeline for benchmarks,
    reports, and other consumers. Decouples business logic from the concrete
    :class:`~lub.pipeline.UncertaintyPipeline` class.

    The protocol is minimal: just the public API surface that downstream
    consumers depend on.
    """

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        """Score a single prompt and return an uncertainty estimate.

        Parameters
        ----------
        prompt : str
            The question to answer.
        **kwargs : Any
            Optional backend-specific parameters passed through to the estimator.

        Returns
        -------
        UncertaintyResult
            Estimate with answer, confidence, and diagnostics.
        """
        ...  # pragma: no cover

    def batch_answer(
        self,
        prompts: list[str],
        **kwargs: Any,
    ) -> list[UncertaintyResult]:
        """Score multiple prompts in sequence.

        Parameters
        ----------
        prompts : list[str]
            List of questions to answer.
        **kwargs : Any
            Optional parameters passed through to :meth:`answer`.

        Returns
        -------
        list[UncertaintyResult]
            List of estimates, one per prompt.
        """
        ...  # pragma: no cover

    def to_dict(self) -> dict[str, Any]:
        """Serialize pipeline configuration to a dict for reproducibility.

        The serialized form must be round-trippable: the caller should be able
        to reconstruct an equivalent pipeline using ``from_dict``.

        Returns
        -------
        dict[str, Any]
            Configuration dict with at least ``backend``, ``model``, and ``estimator`` keys.
        """
        ...  # pragma: no cover


# ===========================================================================
# Relocated from lub.runtime.protocols in RFC-004 (pass 26.9).
# Originally introduced in pass 26.5 (ADR-004); moved here to break the
# agents <-> runtime import cycle. The shim at lub.runtime.protocols
# preserves back-compat imports.
# ===========================================================================


@runtime_checkable
class UncertaintyEstimatorProtocol(Protocol):
    """Minimum interface a uncertainty estimator must satisfy to be
    consumed by ``lub.agents.adapters.orchestrator.from_orchestrator_agent``
    and friends.

    Estimators return a confidence score in ``[0, 1]`` for a given
    ``(prompt, output)`` pair. The score is interpreted by the runtime
    as the model's calibrated confidence in the answer.

    The runtime accepts three return shapes (in order of precedence):

    1. A bare float in ``[0, 1]``.
    2. An object with a ``.confidence`` attribute (a float in ``[0, 1]``).
    3. A dict with a ``"confidence"`` key (a float in ``[0, 1]``).

    Out-of-range values are clamped to ``[0, 1]`` by the runtime.

    Implementations may also support legacy positional signatures
    (``score(output)``, ``__call__(prompt, output)``, etc.); the
    orchestrator adapter falls back to those duck-typed forms when the
    canonical ``score(prompt, output)`` is not available.
    """

    def score(self, prompt: str, output: Any) -> Any:
        """Return a confidence score for the given (prompt, output) pair.

        Args:
            prompt: The prompt rendered to the underlying agent.
            output: The agent's raw output.

        Returns:
            A float in ``[0, 1]``, an object with a ``.confidence``
            attribute, or a dict with a ``"confidence"`` key.
        """
        ...


# ---------------------------------------------------------------------------
# Constants -- centralize what used to be magic strings.
# ---------------------------------------------------------------------------


class AuditKey:
    """Audit-trail keys used by adapters and runtime helpers.

    Centralising the names here means a downstream consumer can write::

        report.audit_trail[AuditKey.ADAPTER]

    instead of guessing the literal string. Any change to a key name
    happens in one place.
    """

    ADAPTER = "adapter"
    ORCHESTRATOR_AGENT = "orchestrator_agent"
    ORCHESTRATOR_AGENT_DESCRIPTION = "orchestrator_agent_description"
    UNCERTAINTY = "uncertainty"
    POLICY = "policy"
    STAGE = "stage"
    UPSTREAM_ERROR = "upstream_error"
    UPSTREAM_MESSAGE = "upstream_message"
    REFUSED = "refused"
    RATIONALE = "rationale"
    LAST_CONFIDENCE = "last_confidence"
    LAST_REFUSAL_FLAGS = "last_refusal_flags"
    LUB_CALIBRATED = "lub_calibrated"
    LUB_AGENT_CLASS = "lub_agent_class"
    TAGS = "tags"


class RefusalAction:
    """Default refusal-action tokens used when a policy gates an output."""

    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
    REDACTED = "[REDACTED]"
    OMIT = "OMIT"
    REFUSED = "REFUSED"


class AdapterLabel:
    """Adapter-name labels used in audit trails.

    Distinct from the orchestrator framework name -- this label
    identifies *which lub adapter* produced the report.
    """

    ORCHESTRATOR = "orchestrator"


__all__ = [
    # Original protocols (pre pass 26.5).
    "BackendProto",
    "PipelineProto",
    "WhiteboxBackendProto",
    # Pass-26.5/26.9: relocated from lub.runtime.protocols to break
    # the agents <-> runtime import cycle (RFC-004).
    "UncertaintyEstimatorProtocol",
    "AuditKey",
    "RefusalAction",
    "AdapterLabel",
]
