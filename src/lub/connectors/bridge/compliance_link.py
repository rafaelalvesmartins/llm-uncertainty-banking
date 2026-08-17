# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Bridge link to :mod:`lub.compliance.frameworks`.

The Bridge platform names three regulatory regimes in its audit docstring
(BCB Resolução 4.893, BCBS 239, SR 11-7) and the platform's per-stage
docstrings reference BCB 4893 eight more times, but until now no module
under :mod:`lub.connectors.bridge` actually imported
:mod:`lub.compliance.frameworks`. The audit ledger could *name* the
regimes it claimed to satisfy, but it could not cite a single concrete
control ID -- the 9-stage pipeline ran completely orphaned from the
seven shipped compliance framework modules.

This module is the missing wire. It imports all seven frameworks
(``bcb_4893``, ``bcbs_239``, ``eu_ai_act``, ``iso_23894``, ``iso_42001``,
``nist_airmf``, ``sr_11_7``), exposes them as the structural
:class:`~lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`,
and provides a defensible default mapping from each Bridge pipeline
stage to the regimes whose controls that stage produces evidence for.
Concretely:

* :class:`BridgeStage` enumerates the nine pipeline stages
  (semantic-cache hit/store, complexity routing, customer memory, RAG
  retrieval, intent classification, agent response, uncertainty guard,
  audit emit, PII governance).
* :class:`ComplianceLinker` returns a :class:`StageEvidence` for any
  stage -- a tuple of framework modules plus the union of control IDs
  drawn from :mod:`lub.reports.crosswalk` -- so an audit event can be
  annotated with concrete control citations instead of free-text
  regime names.

Design notes:

* The default stage-to-regime mapping is *conservative*: it only claims
  the regime if the regime's own scope statement (in its framework
  module's docstring) covers the stage's activity. The mapping is
  surfaced as a constructor argument so a compliance officer can tighten
  or broaden it without editing source.
* SR 11-7 deliberately has ``REGIME = None`` in its framework module
  (see :mod:`lub.compliance.frameworks.sr_11_7`), so this link keys on
  ``CROSSWALK_KEY`` (``"SR_11_7"``) rather than ``Regime``. The structural
  protocol is the contract; the regime enum is an implementation detail
  of crosswalk filtering.
* No I/O, no side effects on import beyond the framework modules' own
  one-time TOML parse. The class is a frozen dataclass so it is safe to
  share across threads in the FastAPI BFF.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

import structlog

from lub.compliance.frameworks import (
    bcb_4893,
    bcbs_239,
    eu_ai_act,
    iso_23894,
    iso_42001,
    nist_airmf,
    sr_11_7,
)
from lub.compliance.frameworks.protocols import ComplianceFrameworkProtocol
from lub.reports.crosswalk import ControlMapping, Regime

logger = structlog.get_logger(__name__)


class BridgeStage(StrEnum):
    """The nine pipeline stages of :class:`~lub.connectors.bridge.BridgePlatform`.

    The order matches the customer-facing flow described in the
    project README and the ``platform.py`` module docstring. Each value
    is the string key used in audit events for that stage.
    """

    SEMANTIC_CACHE_LOOKUP = "semantic_cache_lookup"
    COMPLEXITY_ROUTING = "complexity_routing"
    CUSTOMER_MEMORY = "customer_memory"
    RAG_RETRIEVAL = "rag_retrieval"
    INTENT_CLASSIFICATION = "intent_classification"
    AGENT_RESPONSE = "agent_response"
    UNCERTAINTY_GUARD = "uncertainty_guard"
    SEMANTIC_CACHE_STORE = "semantic_cache_store"
    AUDIT_EMIT = "audit_emit"
    PII_GOVERNANCE = "pii_governance"


_FRAMEWORK_MODULES: tuple[ComplianceFrameworkProtocol, ...] = (
    cast(ComplianceFrameworkProtocol, bcb_4893),
    cast(ComplianceFrameworkProtocol, bcbs_239),
    cast(ComplianceFrameworkProtocol, eu_ai_act),
    cast(ComplianceFrameworkProtocol, iso_23894),
    cast(ComplianceFrameworkProtocol, iso_42001),
    cast(ComplianceFrameworkProtocol, nist_airmf),
    cast(ComplianceFrameworkProtocol, sr_11_7),
)

_BY_KEY: Mapping[str, ComplianceFrameworkProtocol] = MappingProxyType(
    {fw.CROSSWALK_KEY: fw for fw in _FRAMEWORK_MODULES}
)

_BY_REGIME: Mapping[Regime, ComplianceFrameworkProtocol] = MappingProxyType(
    {fw.REGIME: fw for fw in _FRAMEWORK_MODULES if fw.REGIME is not None}
)

# Default stage -> regime CROSSWALK_KEYs. Justification per stage:
#
# * SEMANTIC_CACHE_LOOKUP / _STORE: BCB 4.893 governs retention and
#   reconstructability of automated customer interactions; cached
#   responses must be replayable.
# * COMPLEXITY_ROUTING: BCB 4.893 (cost / operational risk of tier
#   selection); ISO/IEC 42001 (AI management system covering provider
#   selection and lifecycle).
# * CUSTOMER_MEMORY: BCB 4.893 (data retention and access logging for
#   per-customer persona blocks).
# * RAG_RETRIEVAL: BCBS 239 (risk-data aggregation and lineage of the
#   sources cited in the answer); ISO/IEC 23894 (AI risk management
#   covering data quality of retrieval).
# * INTENT_CLASSIFICATION: NIST AI 600-1 (GenAI risk taxonomy);
#   EU AI Act (Article 50 transparency of automated classification).
# * AGENT_RESPONSE: EU AI Act (general AI system obligations);
#   ISO/IEC 42001 (operational controls on the AI service).
# * UNCERTAINTY_GUARD: SR 11-7 (model risk management -- this is the
#   guard whose confidence gates the answer); NIST AI 600-1;
#   ISO/IEC 23894 (AI risk management).
# * AUDIT_EMIT: BCB 4.893 + BCBS 239 + SR 11-7 -- the three regimes
#   the audit module's own docstring names.
# * PII_GOVERNANCE: BCB 4.893 (Brazilian cyber/operational risk includes
#   LGPD-adjacent controls on personal data handling); ISO/IEC 42001
#   (AI management system data governance).
_DEFAULT_STAGE_REGIMES: Mapping[BridgeStage, tuple[str, ...]] = MappingProxyType(
    {
        BridgeStage.SEMANTIC_CACHE_LOOKUP: ("BCB",),
        BridgeStage.SEMANTIC_CACHE_STORE: ("BCB",),
        BridgeStage.COMPLEXITY_ROUTING: ("BCB", "ISO_42001"),
        BridgeStage.CUSTOMER_MEMORY: ("BCB",),
        BridgeStage.RAG_RETRIEVAL: ("BCBS", "ISO_23894"),
        BridgeStage.INTENT_CLASSIFICATION: ("NIST_GENAI", "EU_AI_ACT"),
        BridgeStage.AGENT_RESPONSE: ("EU_AI_ACT", "ISO_42001"),
        BridgeStage.UNCERTAINTY_GUARD: ("SR_11_7", "NIST_GENAI", "ISO_23894"),
        BridgeStage.AUDIT_EMIT: ("BCB", "BCBS", "SR_11_7"),
        BridgeStage.PII_GOVERNANCE: ("BCB", "ISO_42001"),
    }
)


@dataclass(frozen=True)
class StageEvidence:
    """Compliance evidence claimed by one execution of a Bridge stage.

    Attributes:
        stage: The pipeline stage that produced the evidence.
        frameworks: The framework modules whose controls the stage
            asserts evidence for, in declaration order.
        control_ids: The union of control IDs across ``frameworks``,
            de-duplicated while preserving framework declaration order.
            Suitable for direct inclusion in an audit event payload.
    """

    stage: BridgeStage
    frameworks: tuple[ComplianceFrameworkProtocol, ...]
    control_ids: tuple[str, ...]

    def framework_keys(self) -> tuple[str, ...]:
        """Return the ``CROSSWALK_KEY`` of each cited framework."""
        return tuple(fw.CROSSWALK_KEY for fw in self.frameworks)


@dataclass(frozen=True)
class ComplianceLinker:
    """Map Bridge pipeline stages to compliance-framework evidence.

    Construction is zero-cost; the framework modules they reference
    were already imported at module load. Pass ``stage_regimes`` to
    override the conservative default mapping with a tighter (or
    broader) one approved by a compliance officer.
    """

    stage_regimes: Mapping[BridgeStage, tuple[str, ...]] = field(
        default_factory=lambda: dict(_DEFAULT_STAGE_REGIMES)
    )

    @property
    def frameworks(self) -> tuple[ComplianceFrameworkProtocol, ...]:
        """Return all seven shipped compliance framework modules."""
        return _FRAMEWORK_MODULES

    def framework_for_key(self, key: str) -> ComplianceFrameworkProtocol:
        """Return the framework module with ``CROSSWALK_KEY == key``.

        Raises:
            KeyError: If ``key`` is not one of the seven shipped keys
                (``"BCB"``, ``"BCBS"``, ``"EU_AI_ACT"``, ``"ISO_23894"``,
                ``"ISO_42001"``, ``"NIST_GENAI"``, ``"SR_11_7"``).
        """
        return _BY_KEY[key]

    def framework_for_regime(self, regime: Regime) -> ComplianceFrameworkProtocol:
        """Return the framework module backing ``regime``.

        Raises:
            KeyError: If no shipped framework has ``REGIME == regime``.
                SR 11-7 deliberately has ``REGIME = None`` -- look it up
                via :meth:`framework_for_key` with ``"SR_11_7"`` instead.
        """
        return _BY_REGIME[regime]

    def controls_for_key(self, key: str) -> list[ControlMapping]:
        """Return the control mappings the framework asserts."""
        return self.framework_for_key(key).get_controls()

    def evidence_for(self, stage: BridgeStage) -> StageEvidence:
        """Return the compliance evidence claimed by ``stage``.

        The returned :class:`StageEvidence` carries the framework
        modules and the de-duplicated tuple of control IDs each stage
        is mapped to. If ``stage`` has no entry in ``stage_regimes``,
        an empty :class:`StageEvidence` is returned (no exception):
        a stage that produces no compliance evidence is a valid state,
        and the audit module should not have to guard for it.
        """
        keys = self.stage_regimes.get(stage, ())
        frameworks: list[ComplianceFrameworkProtocol] = []
        seen_ids: set[str] = set()
        ordered_ids: list[str] = []
        for key in keys:
            fw = _BY_KEY.get(key)
            if fw is None:
                logger.warning(
                    "bridge.compliance_link.unknown_framework_key",
                    stage=stage.value,
                    key=key,
                )
                continue
            frameworks.append(fw)
            for control in fw.get_controls():
                control_id = control["control_id"]
                if control_id in seen_ids:
                    continue
                seen_ids.add(control_id)
                ordered_ids.append(control_id)
        evidence = StageEvidence(
            stage=stage,
            frameworks=tuple(frameworks),
            control_ids=tuple(ordered_ids),
        )
        logger.debug(
            "bridge.compliance_link.evidence",
            stage=stage.value,
            framework_keys=evidence.framework_keys(),
            n_controls=len(evidence.control_ids),
        )
        return evidence


__all__ = [
    "BridgeStage",
    "ComplianceLinker",
    "StageEvidence",
]
