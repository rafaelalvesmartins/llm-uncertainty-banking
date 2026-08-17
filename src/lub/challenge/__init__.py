# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge -- Continuous Effective Challenge (CEC) for LLM model risk.

The thesis: SR 11-7 expects *effective challenge* -- validation that
actively questions a model's behavior -- but every bank treats it as a
point-in-time event (annual or semi-annual review, document, sign-off,
repeat). LUB's :mod:`lub.ledger` already records every (prompt,
response, UQ scores, policy decision, outcome) tuple. CEC composes
that log into four functions that turn it into a **continuous,
calibrated, executable** effective-challenge process.

Composes:

* :mod:`lub.ledger`               -- substrate
* :mod:`lub.calibration.drift`    -- drift event source
* :mod:`lub.evidence`             -- k-NN historical lookup
* :mod:`lub.mcp`                  -- exposes CEC outputs as MCP tools
* :mod:`lub.reports.mapping`      -- OSCAL emission for AIRMF MANAGE 4.1
                                    + MEASURE 2.7 evidence

Public API
----------

Replay (counterfactual model risk)::

    from lub.challenge import (
        ReplayEngine, AlternativeEstimator,
        AlternativeTier, AlternativeThreshold,
    )

Drift reasoning::

    from lub.challenge import explain_drift_event, DriftHypothesis

Meta-calibration::

    from lub.challenge import MetaCalibrator
    from lub.challenge.meta_calibration import CalibrationCurve

Reports::

    from lub.challenge import CECReport, assemble_cec_report
    from lub.challenge.reports.oscal_export import to_oscal_assessment_results

Spec: ``planning/24_CEC_Spec_2026-04-25.md``.
"""

from __future__ import annotations

from lub.challenge.drift_reasoning import DriftHypothesis, explain_drift_event
from lub.challenge.meta_calibration import CalibrationCurve, MetaCalibrator
from lub.challenge.replay import (
    AlternativeEstimator,
    AlternativeThreshold,
    AlternativeTier,
    ReplayAlternative,
    ReplayEngine,
    ReplayReport,
)
from lub.challenge.reports.cec_report import (
    CECReport,
    assemble_cec_report,
    render_markdown,
)

__all__ = [
    # replay
    "ReplayEngine",
    "ReplayAlternative",
    "AlternativeEstimator",
    "AlternativeTier",
    "AlternativeThreshold",
    "ReplayReport",
    # drift reasoning
    "DriftHypothesis",
    "explain_drift_event",
    # meta-calibration
    "MetaCalibrator",
    "CalibrationCurve",
    # reports
    "CECReport",
    "assemble_cec_report",
    "render_markdown",
]
