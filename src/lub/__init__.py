# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""llm-uncertainty-banking -- uncertainty quantification for LLMs in regulated finance.

Public API
----------

The stable surface is re-exported from this module. Anything not listed
in :attr:`__all__` is internal and may move or rename without a major
version bump.

Pipeline facade::

    from lub import UncertaintyPipeline
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-model",
        backend="dummy",
        estimator="token_logprob",
    )
    result = pipe.answer("What is the Basel III minimum CET1 ratio?")

Governance wrappers::

    from lub import UncertaintyGuard, PolicyDecision
    guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.ABSTAIN)

Introspection::

    from lub import list_backends, list_estimators
    list_backends()   # -> ['anthropic', 'dummy', 'hf', 'openai']
    list_estimators() # -> ['ccp', 'claim_level', ..., 'verbalized_2s']

Result types::

    from lub import UncertaintyResult, BenchmarkResult, GuardResult

Domain exceptions::

    from lub import LubError, BackendError, CapabilityError, ConfidenceParseError
    try:
        result = pipe.answer(prompt)
    except BackendError as e:
        ...  # network/rate-limit/malformed response from LLM

Importing :mod:`lub` bootstraps the backend and estimator registries
as a side effect (via the :mod:`lub.wrappers` and :mod:`lub.uncertainty`
subpackages). Heavy optional backends -- currently :mod:`lub.wrappers.vllm`
-- are NOT loaded eagerly; import them explicitly if you need them.
"""

from importlib.metadata import PackageNotFoundError, version

# Subpackage imports: the subpackages use __getattr__ for lazy loading
# of individual estimator/backend classes, but the base classes and
# registry helpers are always available. The _LAZY_REGISTRY dicts in
# base.py ensure get_estimator_cls / get_backend_cls work without
# eagerly importing all 22+ modules.
import lub.uncertainty  # noqa: F401
import lub.wrappers  # noqa: F401
from lub.challenge import (
    AlternativeEstimator,
    AlternativeThreshold,
    AlternativeTier,
    CalibrationCurve,
    CECReport,
    DriftHypothesis,
    MetaCalibrator,
    ReplayAlternative,
    ReplayEngine,
    ReplayReport,
    assemble_cec_report,
    explain_drift_event,
    render_markdown,
)
from lub.evidence import EvidenceStore, Neighbour, retrieval_adjusted
from lub.exceptions import (
    BackendError,
    BenchmarkError,
    CalibrationError,
    CapabilityError,
    ConfidenceParseError,
    EstimatorError,
    LubError,
    OrchestrationError,
)
from lub.governance import BoundedContext, ContextRegistry, PolicyViolation
from lub.guard import GuardResult, PolicyDecision, PolicyOutcome, UncertaintyGuard
from lub.ledger import Ledger
from lub.orchestration import (
    HookContext,
    HookedPipeline,
    HookRegistry,
    RouterResult,
    SwarmResult,
    Tier,
    TieredRouter,
    UQSwarm,
)
from lub.pipeline import UncertaintyPipeline
from lub.protocols import BackendProto, PipelineProto
from lub.reports.protocol import ReportGenerator
from lub.types import (
    BenchmarkResult,
    Generation,
    TokenLogProbs,
    UncertaintyResult,
)
from lub.uncertainty.base import Estimator, get_estimator_cls, list_estimators
from lub.wrappers.base import ModelBackend, get_backend_cls, list_backends

try:
    __version__ = version("llm-uncertainty-banking")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0+local"

__all__ = [
    "AlternativeEstimator",
    "AlternativeThreshold",
    "AlternativeTier",
    "BackendError",
    "BackendProto",
    "BenchmarkError",
    "BenchmarkResult",
    "BoundedContext",
    "CECReport",
    "CalibrationCurve",
    "CalibrationError",
    "CapabilityError",
    "ConfidenceParseError",
    "ContextRegistry",
    "DriftHypothesis",
    "Estimator",
    "EstimatorError",
    "EvidenceStore",
    "Generation",
    "GuardResult",
    "HookContext",
    "HookRegistry",
    "HookedPipeline",
    "Ledger",
    "LubError",
    "MetaCalibrator",
    "ModelBackend",
    "Neighbour",
    "OrchestrationError",
    "PipelineProto",
    "PolicyDecision",
    "PolicyOutcome",
    "PolicyViolation",
    "ReplayAlternative",
    "ReplayEngine",
    "ReplayReport",
    "ReportGenerator",
    "RouterResult",
    "SwarmResult",
    "Tier",
    "TieredRouter",
    "TokenLogProbs",
    "UQSwarm",
    "UncertaintyGuard",
    "UncertaintyPipeline",
    "UncertaintyResult",
    "__version__",
    "assemble_cec_report",
    "explain_drift_event",
    "get_backend_cls",
    "get_estimator_cls",
    "list_backends",
    "list_estimators",
    "render_markdown",
    "retrieval_adjusted",
]
