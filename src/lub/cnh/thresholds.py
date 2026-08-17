# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.cnh.thresholds -- domain-aware traffic-light thresholds.

A "0.78 confidence" sentence in a legal brief means something different
than the same number in a casual blog post. CNH ships preset thresholds
for four canonical domains plus a helper that resolves a profile from a
:class:`~lub.governance.contexts.BoundedContext` name (legal /
technical / marketing / casual).

Spec: planning/26_CNH_Calibrated_Narrative_Heatmap_2026-04-25.md §3.3.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DomainProfile",
    "LEGAL_PROFILE",
    "TECHNICAL_PROFILE",
    "MARKETING_PROFILE",
    "CASUAL_PROFILE",
    "LEGAL_LIKE_PROFILES",
    "TECHNICAL_LIKE_PROFILES",
    "MARKETING_LIKE_PROFILES",
    "classify",
    "profile_for_context",
]

# Bounded-context name buckets that map to each preset profile. Exposed
# at module level so callers (and other lub domains) can extend them
# without forking ``profile_for_context``. Keep lub itself
# domain-agnostic: do not add petition/immigration-only terms to the
# default sets here -- domain packs should layer their own bucket via
# their own dispatch.
LEGAL_LIKE_PROFILES: frozenset[str] = frozenset({"regulatory", "petition", "legal", "compliance"})
TECHNICAL_LIKE_PROFILES: frozenset[str] = frozenset(
    {"technical", "research", "engineering", "academic"}
)
MARKETING_LIKE_PROFILES: frozenset[str] = frozenset({"marketing", "outreach", "sales"})


@dataclass(frozen=True)
class DomainProfile:
    """Traffic-light thresholds for one domain.

    A confidence at or above ``green_min`` renders green; at or above
    ``yellow_min`` renders yellow; below ``yellow_min`` renders red.
    """

    name: str
    green_min: float
    yellow_min: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.yellow_min <= self.green_min <= 1.0):
            raise ValueError(
                f"DomainProfile {self.name!r}: must satisfy "
                f"0 <= yellow_min ({self.yellow_min}) <= "
                f"green_min ({self.green_min}) <= 1"
            )


# Strictest -> most permissive
LEGAL_PROFILE = DomainProfile(name="legal", green_min=0.90, yellow_min=0.70)
TECHNICAL_PROFILE = DomainProfile(name="technical", green_min=0.80, yellow_min=0.60)
MARKETING_PROFILE = DomainProfile(name="marketing", green_min=0.70, yellow_min=0.50)
CASUAL_PROFILE = DomainProfile(name="casual", green_min=0.60, yellow_min=0.40)


def classify(confidence: float, profile: DomainProfile = LEGAL_PROFILE) -> str:
    """Return ``"green"`` / ``"yellow"`` / ``"red"`` for *confidence* under *profile*."""
    if confidence >= profile.green_min:
        return "green"
    if confidence >= profile.yellow_min:
        return "yellow"
    return "red"


def profile_for_context(context_name: str | None) -> DomainProfile:
    """Resolve a :class:`DomainProfile` from a bounded-context name.

    Names matching ``regulatory`` / ``petition`` / ``legal`` map to
    :data:`LEGAL_PROFILE`. ``technical`` / ``research`` map to
    :data:`TECHNICAL_PROFILE`. ``marketing`` / ``outreach`` map to
    :data:`MARKETING_PROFILE`. Anything else (including ``None``) maps
    to :data:`CASUAL_PROFILE`.
    """
    if not context_name:
        return CASUAL_PROFILE
    lower = context_name.lower().strip()
    if lower in LEGAL_LIKE_PROFILES:
        return LEGAL_PROFILE
    if lower in TECHNICAL_LIKE_PROFILES:
        return TECHNICAL_PROFILE
    if lower in MARKETING_LIKE_PROFILES:
        return MARKETING_PROFILE
    return CASUAL_PROFILE
