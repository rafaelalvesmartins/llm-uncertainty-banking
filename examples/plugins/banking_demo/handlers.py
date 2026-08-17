# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Handlers for the banking_demo plugin.

This file demonstrates the ruflo plugin convention used by
:func:`lub.mcp.tools.plugin_loader.discover_ruflo_plugins`:

* Export a ``HANDLERS`` dict mapping tool names (matching the
  ``manifest.json`` ``tools[].name`` entries) to callables of shape
  ``(args: dict[str, Any]) -> dict[str, Any]``.
* The lub plugin loader reads ``manifest.json``, imports this module,
  validates that every manifest tool has a handler, and adapts each
  pair into a lub MCP :class:`ToolDef`.

To install: drop the parent ``banking_demo/`` folder into
``~/.lub/plugins/`` (or set ``$LUB_PLUGINS_DIR`` to a directory that
contains it). On the next ``build_server()`` call, both tools appear
in the catalog as:

* ``ruflo.banking-demo.sr_11_7_check``
* ``ruflo.banking-demo.regime_lookup``
"""

from __future__ import annotations

from typing import Any


# Calibrated-metric vocabulary the SR 11-7 auditor scaffold flags. A real
# implementation would parse the claim, route it to a CalibratedAgent
# scoring pipeline, and return a structured verdict; this stand-in just
# does keyword detection so the plugin round-trip is observable.
_CALIBRATED_METRIC_TERMS = (
    "ece",
    "expected calibration error",
    "brier",
    "auroc",
    "crps",
    "conformal",
    "p(true)",
    "semantic entropy",
)


def _sr_11_7_check(args: dict[str, Any]) -> dict[str, Any]:
    claim = str(args.get("claim", "")).lower()
    cites_calibration = any(term in claim for term in _CALIBRATED_METRIC_TERMS)
    return {
        "verdict": "passes" if cites_calibration else "uncalibrated_claim",
        "rationale": (
            "Claim references a calibrated metric."
            if cites_calibration
            else "Claim asserts model performance without a calibrated metric — "
                 "SR 11-7 §III.A requires conceptual soundness backed by quantitative "
                 "evidence."
        ),
        "matched_terms": [t for t in _CALIBRATED_METRIC_TERMS if t in claim],
    }


# Mirror of the canonical regime set in lub.reports.crosswalk_data.toml.
# Keeps the plugin self-contained — the demo doesn't need to import lub
# at handler time, but a production plugin would resolve through
# `lub.reports.crosswalk.regimes()` to stay in sync with the toml.
_REGIME_TABLE: dict[str, dict[str, str]] = {
    "nist":     {"enum": "NIST_GENAI", "title": "NIST AI 600-1 (Generative AI Profile of AI RMF 1.0)"},
    "eu":       {"enum": "EU_AI_ACT",  "title": "Regulation (EU) 2024/1689 (EU AI Act)"},
    "bcbs":     {"enum": "BCBS",       "title": "BCBS 239 (Principles for effective risk data aggregation and risk reporting)"},
    "bcb":      {"enum": "BCB",        "title": "BCB Resolução 4.893/2021"},
    "iso23894": {"enum": "ISO_23894",  "title": "ISO/IEC 23894:2023 (AI risk management)"},
    "iso42001": {"enum": "ISO_42001",  "title": "ISO/IEC 42001:2023 (AI management system)"},
}


def _regime_lookup(args: dict[str, Any]) -> dict[str, Any]:
    short = str(args.get("regime", "")).lower().strip()
    entry = _REGIME_TABLE.get(short)
    if entry is None:
        return {
            "found": False,
            "input": short,
            "valid_keys": sorted(_REGIME_TABLE.keys()),
        }
    return {"found": True, **entry}


HANDLERS: dict[str, Any] = {
    "sr_11_7_check": _sr_11_7_check,
    "regime_lookup": _regime_lookup,
}
