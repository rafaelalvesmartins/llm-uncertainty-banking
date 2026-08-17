# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Hermetic tests for ``lub.governance.calibration_targets`` (Pattern 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.governance.adr import PolicyViolation
from lub.governance.calibration_targets import CalibrationTargets

# ---------------------------------------------------------------------------
# Construction + from_mapping
# ---------------------------------------------------------------------------


def test_construction_minimal():
    t = CalibrationTargets(
        max_ece=0.05,
        min_refusal_auroc=0.75,
        max_inference_p95_ms=2000,
        min_coverage=0.85,
        max_risk=0.02,
    )
    assert t.max_ece == 0.05
    assert t.min_refusal_auroc == 0.75


def test_from_mapping_uses_adr_keys():
    t = CalibrationTargets.from_mapping({
        "calibration_target_ece": 0.03,
        "coverage_target": 0.7,
        "risk_ceiling": 0.01,
    })
    assert t.max_ece == 0.03
    assert t.min_coverage == 0.7
    assert t.max_risk == 0.01


def test_from_mapping_uses_dataclass_keys_when_adr_keys_missing():
    t = CalibrationTargets.from_mapping({
        "max_ece": 0.04,
        "min_coverage": 0.8,
        "max_risk": 0.05,
    })
    assert t.max_ece == 0.04
    assert t.min_coverage == 0.8


def test_from_mapping_supplies_defaults_for_missing_fields():
    # Fields not declared in either alias get the conservative defaults.
    t = CalibrationTargets.from_mapping({})
    assert t.min_refusal_auroc == 0.70
    assert t.max_inference_p95_ms == 5000


# ---------------------------------------------------------------------------
# from_adr — full ADR YAML parsing
# ---------------------------------------------------------------------------


def _write_adr(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "0001-test.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_from_adr_parses_per_context_invariants(tmp_path):
    p = _write_adr(tmp_path, """---
id: "0001"
title: "test"
status: accepted
date: 2026-04-25
invariants:
  regulatory-qa:
    calibration_target_ece: 0.03
    coverage_target: 0.70
    risk_ceiling: 0.01
  retail-credit:
    calibration_target_ece: 0.05
    coverage_target: 0.85
    risk_ceiling: 0.03
---

# body
""")
    out = CalibrationTargets.from_adr(p)
    assert set(out.keys()) == {"regulatory-qa", "retail-credit"}
    assert out["regulatory-qa"].max_ece == 0.03
    assert out["retail-credit"].min_coverage == 0.85


def test_from_adr_empty_invariants_returns_empty_dict(tmp_path):
    p = _write_adr(tmp_path, """---
id: "0001"
title: "no invariants"
status: accepted
date: 2026-04-25
---

# body
""")
    assert CalibrationTargets.from_adr(p) == {}


def test_from_adr_missing_frontmatter_raises(tmp_path):
    p = tmp_path / "broken.md"
    p.write_text("# no front matter", encoding="utf-8")
    with pytest.raises(ValueError, match="front-matter"):
        CalibrationTargets.from_adr(p)


def test_from_adr_skips_non_mapping_invariant_entries(tmp_path):
    p = _write_adr(tmp_path, """---
id: "0001"
title: "mixed"
status: accepted
date: 2026-04-25
invariants:
  regulatory-qa:
    calibration_target_ece: 0.03
  scalar_invariant: 1.5
  list_invariant:
    - a
    - b
---

# body
""")
    out = CalibrationTargets.from_adr(p)
    assert "regulatory-qa" in out
    assert "scalar_invariant" not in out
    assert "list_invariant" not in out


def test_from_adr_against_real_repo_adr_0001():
    # If the real ADR 0001 exists, it must parse without error.
    real = Path(__file__).resolve().parents[2] / "docs" / "adr" / "0001-calibration-targets.md"
    if real.exists():
        out = CalibrationTargets.from_adr(real)
        # Must produce at least one context (the ADR ships with several).
        assert len(out) >= 1


# ---------------------------------------------------------------------------
# assert_against
# ---------------------------------------------------------------------------


def _targets() -> CalibrationTargets:
    return CalibrationTargets(
        max_ece=0.05,
        min_refusal_auroc=0.70,
        max_inference_p95_ms=1000,
        min_coverage=0.80,
        max_risk=0.05,
    )


def test_assert_passes_when_metrics_within_targets():
    t = _targets()
    t.assert_against({
        "ece": 0.04,
        "refusal_auroc": 0.85,
        "inference_p95_ms": 800,
        "coverage": 0.90,
        "risk": 0.02,
    })


def test_assert_passes_with_missing_metrics():
    # Only the metrics actually provided are checked.
    t = _targets()
    t.assert_against({"ece": 0.03})


def test_assert_violates_on_high_ece():
    t = _targets()
    with pytest.raises(PolicyViolation, match="ece"):
        t.assert_against({"ece": 0.99})


def test_assert_violates_on_low_refusal_auroc():
    t = _targets()
    with pytest.raises(PolicyViolation, match="refusal_auroc"):
        t.assert_against({"refusal_auroc": 0.5})


def test_assert_violates_on_high_latency():
    t = _targets()
    with pytest.raises(PolicyViolation, match="inference_p95_ms"):
        t.assert_against({"inference_p95_ms": 10_000})


def test_assert_violates_on_low_coverage():
    t = _targets()
    with pytest.raises(PolicyViolation, match="coverage"):
        t.assert_against({"coverage": 0.1})


def test_assert_violates_on_high_risk():
    t = _targets()
    with pytest.raises(PolicyViolation, match="risk"):
        t.assert_against({"risk": 0.99})


def test_assert_violates_on_first_breach_only():
    # When multiple metrics breach, the first checked one raises.
    t = _targets()
    with pytest.raises(PolicyViolation):
        t.assert_against({"ece": 0.99, "risk": 0.99})


# ---------------------------------------------------------------------------
# Frozen contract
# ---------------------------------------------------------------------------


def test_targets_are_frozen():
    t = _targets()
    with pytest.raises(Exception):
        t.max_ece = 0.99  # type: ignore[misc]
