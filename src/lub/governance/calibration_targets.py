# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Calibration targets baked into config (Pattern 4).

Formalizes ``docs/adr/0001-calibration-targets.md`` — which currently
declares per-context targets in YAML front-matter — as a Python class
that CI can assert against. The dataclass is the runtime view; the
ADR file remains the source of truth for *what* the targets are.

Five dimensions per context:

* ``max_ece`` — upper bound on Expected Calibration Error.
* ``min_refusal_auroc`` — lower bound on the refusal ranker's AUROC.
* ``max_inference_p95_ms`` — latency ceiling at the 95th percentile.
* ``min_coverage`` — fraction of queries the runtime answers without
  abstaining.
* ``max_risk`` — maximum acceptable error rate on answered queries.

Defaults for fields not declared in the ADR YAML use the
"conservative" tier: ``min_refusal_auroc=0.70``, ``max_inference_p95_ms=5000``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lub.governance.adr import PolicyViolation

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n.*$", re.DOTALL)

_DEFAULT_MIN_REFUSAL_AUROC = 0.70
_DEFAULT_MAX_INFERENCE_P95_MS = 5000


@dataclass(frozen=True)
class CalibrationTargets:
    """Per-context numeric targets that CI can assert against.

    All fields are upper / lower bounds; ``assert_against`` raises
    :class:`PolicyViolation` when a metric breaches its target.
    """

    max_ece: float
    min_refusal_auroc: float
    max_inference_p95_ms: int
    min_coverage: float
    max_risk: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> CalibrationTargets:
        """Build a single :class:`CalibrationTargets` from a flat mapping."""
        return cls(
            max_ece=float(data.get("calibration_target_ece", data.get("max_ece", 0.10))),
            min_refusal_auroc=float(data.get("min_refusal_auroc", _DEFAULT_MIN_REFUSAL_AUROC)),
            max_inference_p95_ms=int(
                data.get("max_inference_p95_ms", _DEFAULT_MAX_INFERENCE_P95_MS)
            ),
            min_coverage=float(data.get("coverage_target", data.get("min_coverage", 0.0))),
            max_risk=float(data.get("risk_ceiling", data.get("max_risk", 1.0))),
        )

    @classmethod
    def from_adr(cls, path: Path) -> dict[str, CalibrationTargets]:
        """Parse ``docs/adr/0001-calibration-targets.md``.

        Returns one :class:`CalibrationTargets` per bounded context.
        Empty dict if the ADR has no ``invariants:`` block or it
        doesn't list contexts.
        """
        text = Path(path).read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise ValueError(f"ADR {path} missing YAML front-matter")
        front = yaml.safe_load(m.group(1)) or {}
        invariants = front.get("invariants") or {}
        out: dict[str, CalibrationTargets] = {}
        for ctx_name, ctx_data in invariants.items():
            if isinstance(ctx_data, Mapping):
                out[ctx_name] = cls.from_mapping(ctx_data)
        return out

    def assert_against(self, metrics: Mapping[str, Any]) -> None:
        """Raise :class:`PolicyViolation` if any metric breaches a target.

        Recognized metric keys (others are ignored):

        * ``ece`` — must be ``<= max_ece``
        * ``refusal_auroc`` — must be ``>= min_refusal_auroc``
        * ``inference_p95_ms`` — must be ``<= max_inference_p95_ms``
        * ``coverage`` — must be ``>= min_coverage``
        * ``risk`` — must be ``<= max_risk``
        """
        if "ece" in metrics and float(metrics["ece"]) > self.max_ece:
            raise PolicyViolation(f"ece {metrics['ece']:.4f} > max_ece {self.max_ece:.4f}")
        if "refusal_auroc" in metrics and float(metrics["refusal_auroc"]) < self.min_refusal_auroc:
            raise PolicyViolation(
                f"refusal_auroc {metrics['refusal_auroc']:.4f} < "
                f"min_refusal_auroc {self.min_refusal_auroc:.4f}"
            )
        if (
            "inference_p95_ms" in metrics
            and int(metrics["inference_p95_ms"]) > self.max_inference_p95_ms
        ):
            raise PolicyViolation(
                f"inference_p95_ms {metrics['inference_p95_ms']} > max {self.max_inference_p95_ms}"
            )
        if "coverage" in metrics and float(metrics["coverage"]) < self.min_coverage:
            raise PolicyViolation(
                f"coverage {metrics['coverage']:.4f} < min_coverage {self.min_coverage:.4f}"
            )
        if "risk" in metrics and float(metrics["risk"]) > self.max_risk:
            raise PolicyViolation(f"risk {metrics['risk']:.4f} > max_risk {self.max_risk:.4f}")


__all__ = ["CalibrationTargets"]
