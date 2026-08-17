# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Backward-compatibility re-export shim -- framework-level policy enum.

Policy types live in :mod:`lub.guard`. This module re-exports them so
existing ``from lub.policies import ...`` statements keep working.

The framework-level ``PolicyDecision`` here is an enum
(``ABSTAIN | FLAG | PASSTHROUGH | RAISE``), distinct from the
agent-side dataclass with the same name in :mod:`lub.agents.policies`.
"""

from lub.guard import PolicyDecision, PolicyOutcome, rmf_subcategory

__all__ = ["PolicyDecision", "PolicyOutcome", "rmf_subcategory"]
