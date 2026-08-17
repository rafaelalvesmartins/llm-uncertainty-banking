# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""L3 — calibration metrics and plots.

Pure numpy/matplotlib. No dependency on L1 (wrappers) or L2 (uncertainty),
so these functions can be used stand-alone on any ``(confidences, correct)``
arrays — including outputs from systems that are not ``lub`` pipelines.
"""

from lub.calibration.drift import (
    CBPEEstimate,
    DriftProfile,
    DriftReport,
    DriftSeverity,
    analyze_drift,
    population_stability_index,
)
from lub.calibration.linguistic import (
    extract_implied_probability,
    linguistic_calibration_report,
    linguistic_calibration_score,
)
from lub.calibration.metrics import (
    adversarial_group_calibration,
    brier_score,
    compute_all,
    expected_calibration_error,
    expected_normalized_calibration_error,
    kendall_tau,
    matthews_correlation,
    miscalibration_area,
    missing_ratio,
    refusal_auroc,
    reliability_curve,
    reversed_pairs_proportion,
    root_mean_squared_calibration_error,
    sharpness,
    spearman_rank_correlation,
)
from lub.calibration.normalizers import (
    BinnedPCCNormalizer,
    IdentityNormalizer,
    IsotonicNormalizer,
    MinMaxNormalizer,
    Normalizer,
    QuantileNormalizer,
    load_normalizer,
)
from lub.calibration.plots import (
    plot_confidence_histogram,
    plot_reliability_diagram,
    plot_risk_coverage,
    save_figure,
)
from lub.calibration.scoring_rules import (
    crps_from_confidence,
    crps_gaussian,
    interval_score,
    negative_log_likelihood,
    pinball_loss,
)
from lub.calibration.selective import (
    area_under_risk_coverage,
    prediction_rejection_ratio,
    risk_coverage_curve,
)

# ---------------------------------------------------------------------------
# Default bin counts -- exposed as constants so call sites can be audited
# and users can override consistently across calibration / drift code.
#
# The values match the literals previously hard-coded in the functions
# below; we keep them synchronised so changing the constant moves both
# code paths together. Function signatures still carry the literal as
# default for backward compatibility (mypy / Sphinx can resolve it).
# ---------------------------------------------------------------------------

#: Default bin count for calibration metrics (ECE, RMSCE, ENCE, reliability
#: curve, etc.). 15 mirrors the choice in Guo et al. 2017 ("On Calibration
#: of Modern Neural Networks") and Nguyen and O'Connor 2015. Used by
#: :mod:`lub.calibration.metrics` and :class:`BinnedPCCNormalizer`.
DEFAULT_RELIABILITY_BINS: int = 15

#: Default bin count for drift profiles (population-stability index,
#: confidence-distribution histograms). 20 follows the convention in
#: Section 3 of Webb et al. 2016 ("Characterizing concept drift") --
#: finer granularity than reliability bins because drift is typically
#: looked at on the *empirical* (not calibrated) score distribution.
#: Used by :mod:`lub.calibration.drift`.
DEFAULT_DRIFT_PROFILE_BINS: int = 20


# ``prr`` is a short alias for :func:`prediction_rejection_ratio`, kept as
# a convenience for benchmark-result dicts that want a compact key name.
prr = prediction_rejection_ratio

__all__ = [
    "CBPEEstimate",
    "DEFAULT_DRIFT_PROFILE_BINS",
    "DEFAULT_RELIABILITY_BINS",
    "DriftProfile",
    "DriftReport",
    "DriftSeverity",
    "analyze_drift",
    "BinnedPCCNormalizer",
    "IdentityNormalizer",
    "IsotonicNormalizer",
    "MinMaxNormalizer",
    "Normalizer",
    "QuantileNormalizer",
    "adversarial_group_calibration",
    "area_under_risk_coverage",
    "brier_score",
    "compute_all",
    "crps_from_confidence",
    "crps_gaussian",
    "expected_calibration_error",
    "expected_normalized_calibration_error",
    "extract_implied_probability",
    "interval_score",
    "kendall_tau",
    "linguistic_calibration_report",
    "linguistic_calibration_score",
    "load_normalizer",
    "matthews_correlation",
    "miscalibration_area",
    "missing_ratio",
    "negative_log_likelihood",
    "pinball_loss",
    "population_stability_index",
    "plot_confidence_histogram",
    "plot_reliability_diagram",
    "plot_risk_coverage",
    "prediction_rejection_ratio",
    "prr",
    "refusal_auroc",
    "reliability_curve",
    "reversed_pairs_proportion",
    "risk_coverage_curve",
    "root_mean_squared_calibration_error",
    "save_figure",
    "sharpness",
    "spearman_rank_correlation",
]
