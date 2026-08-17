# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""lub.domains -- pluggable domain extensions.

Originally introduced in spec 30 (pass 30) as an empty namespace;
since pass 33 (CHANGES_2026-04-26 §1.11) it ships a single skeleton
sub-namespace, :mod:`lub.domains.banking`, which lazy-aliases the
banking-domain benchmark modules (``finqa``, ``convfinqa``, ``tatqa``,
``credit_scoring``, ``financial_sentiment``, ``br_regulatory``) under
the v0.3-shaped path so v0.3-targeted code already works on v0.1.

The generic core (``lub.benchmarks``, ``lub.uncertainty``,
``lub.calibration``, ``lub.reports``, ...) stays domain-blind;
domain-specific artifacts (healthcare prompts, defense scenarios)
will land here as additional ``lub.domains.<name>`` skeletons before
the v0.3 module move.

See ``planning/30_Generic_Architecture_Spec_2026-04-25.md``.
"""

from __future__ import annotations

from lub.domains import banking  # noqa: F401

__all__: list[str] = ["banking"]
