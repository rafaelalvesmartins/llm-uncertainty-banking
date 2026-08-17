# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""lub.compliance -- pluggable regulatory / compliance frameworks.

Originally introduced in spec 30 (pass 30) as an empty namespace;
since pass 33 (CHANGES_2026-04-26 §1.11) it ships the
:mod:`lub.compliance.frameworks` skeleton with seven framework
modules (SR 11-7, NIST AI RMF, ISO/IEC 42001, EU AI Act, BCBS 239,
BCB 4893, ISO/IEC 23894) plus the structural
:class:`~lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`.

Each compliance framework eventually owns its own control catalog,
optional emit format, and crosswalk to the others under
``lub.compliance.frameworks.<name>``; v0.1 keeps the consolidated
data side under :mod:`lub.reports.crosswalk` + ``crosswalk_data.toml``
so this namespace is mostly metadata pointers and the Protocol
contract.  v0.3 will migrate per-framework catalogs here.

See ``planning/30_Generic_Architecture_Spec_2026-04-25.md``.
"""

from __future__ import annotations

from lub.compliance import frameworks  # noqa: F401

__all__: list[str] = ["frameworks"]
