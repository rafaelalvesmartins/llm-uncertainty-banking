# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""lub.domains.banking -- banking-domain artifact namespace (skeleton, v0.3+).

Per spec 30 (`planning/30_Generic_Architecture_Spec_2026-04-25.md`)
the banking-specific benchmarks should eventually live here so the
core ``lub.benchmarks`` package can stay domain-blind. v0.1 keeps the
artifacts where they are (under ``lub.benchmarks``) and re-exports
them from this namespace as **lazy aliases**, so:

* code targeting the v0.3 layout already imports from
  ``lub.domains.banking`` and works unchanged on v0.1;
* the v0.1 import surface is unchanged (no module moves);
* the migration is mechanical when v0.3 lands -- flip the alias to
  point at the new home and drop a ``DeprecationWarning`` on the old
  paths.

Surface today
-------------

>>> from lub.domains.banking import (
...     finqa, convfinqa, tatqa,
...     credit_scoring, financial_sentiment, br_regulatory,
... )

These names re-export the same modules currently at ``lub.benchmarks.*``.
"""

from __future__ import annotations

from types import ModuleType

# Re-export the banking-domain benchmark modules under the future path.
# Imported as modules (not symbols) so callers can reach into them the
# same way they would on v0.3 (e.g. ``banking.finqa.FinQADataset``).
from lub.benchmarks import (  # noqa: F401
    br_regulatory,
    convfinqa,
    credit_scoring,
    financial_sentiment,
    finqa,
    tatqa,
)

#: Tuple of every shipped banking-domain benchmark module, in stable
#: alphabetical order. Mirror of
#: :data:`lub.compliance.frameworks.FRAMEWORKS` on the domain axis of
#: the spec-30 plug-in matrix. Consumers that iterate over the
#: banking-domain benchmarks (the dashboard's per-benchmark cards,
#: future cross-benchmark reporters) can use this tuple instead of
#: hard-coding the six concrete names.
BENCHMARKS: tuple[ModuleType, ...] = (
    br_regulatory,
    convfinqa,
    credit_scoring,
    financial_sentiment,
    finqa,
    tatqa,
)

__all__ = [
    "BENCHMARKS",
    "br_regulatory",
    "convfinqa",
    "credit_scoring",
    "financial_sentiment",
    "finqa",
    "tatqa",
]
