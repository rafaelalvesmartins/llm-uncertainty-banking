# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Methodological grouping of the 22 uncertainty estimators into 7 families.

The README and the petition narrative both reference the framework as
"22 estimators in 7 methodological families". Until now that grouping
lived only in prose — this module materialises it as code so callers
(SR 11-7 compliance dashboards, audit reports, OSCAL emission) can
iterate families and estimators programmatically rather than re-parsing
the README.

Family definitions mirror the README §"Uncertainty estimators" verbatim:

* **information-based** — token-level log-probability signals.
* **diversity-based** — sample-and-cluster / ensemble agreement.
* **conformal** — distribution-free coverage guarantees.
* **reflexive** — model self-assessment via meta-question prompting.
* **verbalized** — model self-reported confidence in natural language.
* **density-based** — geometric / spectral feature-space signals.
* **claim-level + epistemic** — per-claim coverage and Bayesian /
  MC-dropout approximations.

The membership lists are the public class names exported through
:mod:`lub.uncertainty.__all__`; the adapter ``LMPolygraphEstimator``
is intentionally *not* listed because it is a third-party-wrapper
adapter, not an in-house method.

Verification:

>>> from lub.uncertainty.families import FAMILIES, all_estimators_by_family
>>> sum(len(v) for v in FAMILIES.values())
22
>>> len(FAMILIES)
7
"""

from __future__ import annotations

from typing import Final

#: Family name → ordered tuple of estimator class names. Order matches
#: the README narrative so an OSCAL emitter can render families in the
#: same sequence the documentation cites.
FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "information-based": (
        "TokenLogprobEstimator",
        "PerplexityEstimator",
        "TokenSAREstimator",
        "SentenceSAREstimator",
    ),
    "diversity-based": (
        "SelfConsistencyEstimator",
        "SemanticEntropyEstimator",
        "EigenScoreEstimator",
        "EnsembleEstimator",
        "SelfCertaintyEstimator",
    ),
    "conformal": (
        "ConformalEstimator",
        "AdaptiveConformalEstimator",
        "MondrianConformalEstimator",
        "ConformalSamplingEstimator",
        "CCPEstimator",
    ),
    "reflexive": (
        "PTrueEstimator",
    ),
    "verbalized": (
        "VerbalizedOneShot",
        "VerbalizedTwoShot",
    ),
    "density-based": (
        "MahalanobisEstimator",
        "GraphLaplacianEstimator",
        "EpistemicAleatoricEstimator",
    ),
    "claim-level-and-epistemic": (
        "ClaimLevelEstimator",
        "MCDropoutEstimator",
    ),
}


def all_estimators_by_family() -> dict[str, tuple[str, ...]]:
    """Return a copy of the FAMILIES mapping (defensive copy)."""
    return {family: tuple(members) for family, members in FAMILIES.items()}


def family_of(estimator_name: str) -> str | None:
    """Return the family containing ``estimator_name``, or ``None``."""
    for family, members in FAMILIES.items():
        if estimator_name in members:
            return family
    return None


def estimator_count() -> int:
    """Total count across all families (must equal 22 — petition claim)."""
    return sum(len(members) for members in FAMILIES.values())


def family_count() -> int:
    """Number of families (must equal 7 — petition claim)."""
    return len(FAMILIES)


__all__ = [
    "FAMILIES",
    "all_estimators_by_family",
    "estimator_count",
    "family_count",
    "family_of",
]
