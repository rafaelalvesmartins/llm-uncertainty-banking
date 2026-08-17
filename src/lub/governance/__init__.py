# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Governance: ADRs as enforced specs + DDD bounded contexts.

Ruflo uses Architecture Decision Records as runtime guardrails. LUB
adopts the same pattern, scoped to calibration policy: each bounded
context (retail-credit, regulatory-qa, fraud-alerts, investor-advisory)
declares its calibration target, coverage target, risk ceiling, and
tier order. An ADR is the canonical document; :class:`BoundedContext`
is its runtime handle.

The goal is "AI governance as code": a failing calibration ADR is a
failing CI job, not a PDF buried in a compliance folder.
"""

from __future__ import annotations

from lub.governance.adr import ADR, ADRRegistry, PolicyViolation, assert_policy
from lub.governance.calibration_targets import CalibrationTargets
from lub.governance.contexts import BoundedContext, ContextRegistry
from lub.governance.drift import DriftReport, check_drift, compute_ece, enforce_drift

__all__ = [
    "ADR",
    "ADRRegistry",
    "BoundedContext",
    "CalibrationTargets",
    "ContextRegistry",
    "DriftReport",
    "PolicyViolation",
    "assert_policy",
    "check_drift",
    "compute_ece",
    "enforce_drift",
]
