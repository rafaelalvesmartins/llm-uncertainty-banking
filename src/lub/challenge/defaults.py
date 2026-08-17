# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Centralized default values for the ``lub.challenge`` package.

Pattern 1.6 from ``planning/26_Decoupling_Refactor_Plan_2026-04-25.md``.

These constants name *soft* invariants — reasonable defaults that
callers can override at every call site. They live here, not scattered
across the consumer modules, so:

1. A future ADR (or `docs/adr/0001-calibration-targets.md`) can declare
   them as machine-checkable invariants for `lub.governance.assert_policy`.
2. A bank tuning the runtime to its own risk appetite changes one file,
   not five.
3. CI can detect drift by snapshotting this module against a pinned
   reference.

If you find yourself adding a magic literal in `lub.challenge.*`, add
it here first.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Replay engine (`lub.challenge.replay.ReplayEngine`)
# ---------------------------------------------------------------------------

#: Confidence threshold above which the baseline "would have answered"
#: in a counterfactual replay. Counterfactuals below this threshold
#: become ABSTAIN. 0.90 corresponds to a high-conviction policy default
#: consistent with ADR 0001's regulatory-qa context.
REPLAY_BASELINE_THRESHOLD: Final[float] = 0.90

#: UQ score channel used for the baseline. `"confidence"` selects the
#: post-calibration confidence column; `"p_true"` would select the
#: P(True) self-rating channel; etc.
REPLAY_SCORE_METHOD: Final[str] = "confidence"

# ---------------------------------------------------------------------------
# Context Autopilot ejection (`lub.challenge.context_autopilot.ejection`)
# ---------------------------------------------------------------------------

#: Weight on the (1 - similarity) term in the ejection score. Higher
#: alpha → eject content unrelated to the current query more aggressively.
EJECTION_ALPHA: Final[float] = 0.5

#: Weight on the age-in-turns term. Higher beta → eject older content
#: faster (LRU-like behaviour).
EJECTION_BETA: Final[float] = 0.2

#: Weight on the historical_usefulness term (subtracted from the score).
#: Higher gamma → preserve content that historically led to correct
#: answers.
EJECTION_GAMMA: Final[float] = 0.3

#: Minimum ejection score required to actually eject a turn. Floor
#: at 0 keeps the system from ejecting on weak signal.
EJECTION_THRESHOLD: Final[float] = 0.5

#: Cold-start usefulness prior — used when k-NN over `cec_meta_outcomes`
#: returns no matches. 0.5 is uninformative; biases neither for nor
#: against ejection.
EJECTION_COLD_START_USEFULNESS: Final[float] = 0.5

# ---------------------------------------------------------------------------
# Context Autopilot recall (`lub.challenge.context_autopilot.recall`)
# ---------------------------------------------------------------------------

#: Number of nearest neighbours to consider when deciding whether a
#: later turn is recalling ejected content. 3 is small enough to stay
#: hermetic in tests, large enough to catch obvious recall patterns.
RECALL_K_NEIGHBOURS: Final[int] = 3

#: Minimum cosine similarity to flag a recall risk. Below this the
#: similarity is treated as noise.
RECALL_SIMILARITY_THRESHOLD: Final[float] = 0.3

#: Default headroom ratio below which Context Autopilot considers the
#: budget tight enough to evaluate ejections. Above this ratio,
#: ejection is skipped (no pressure).
HEADROOM_TIGHT_THRESHOLD: Final[float] = 0.15

# ---------------------------------------------------------------------------
# Meta-calibration (`lub.challenge.meta_calibration`)
# ---------------------------------------------------------------------------

#: Number of bins the reliability curve uses when computing ECE on
#: meta-calibration outcomes. 10 deciles is the SR 11-7 commentariat
#: convention.
META_CALIBRATION_BIN_COUNT: Final[int] = 10


__all__ = [
    "REPLAY_BASELINE_THRESHOLD",
    "REPLAY_SCORE_METHOD",
    "EJECTION_ALPHA",
    "EJECTION_BETA",
    "EJECTION_GAMMA",
    "EJECTION_THRESHOLD",
    "EJECTION_COLD_START_USEFULNESS",
    "RECALL_K_NEIGHBOURS",
    "RECALL_SIMILARITY_THRESHOLD",
    "HEADROOM_TIGHT_THRESHOLD",
    "META_CALIBRATION_BIN_COUNT",
]
