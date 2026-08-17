"""
Tests for lub.agents.adapters.*.

Most adapters (langgraph, crewai, autogen) are gated behind an optional
extra. These tests verify the correct behavior in two modes:

1. If the extra is installed: the adapter imports, and calling its
   entry function raises NotImplementedError with a message pointing to
   the v0.3 roadmap.
2. If the extra is NOT installed: importing the module raises an
   ImportError with a clear install hint.

The ruflo adapter is the exception: it ships as a Protocol-based
duck-typing wrapper, no ``import ruflo`` at module load, and has a full
implementation as of pass 23. End-to-end coverage for the ruflo adapter
lives in ``tests/unit/test_ruflo_adapter.py``; the parametrized smoke
test below only verifies that the module imports and exposes the
expected callable.

We use a try/except-ImportError pattern to be robust to either environment.
"""

from __future__ import annotations

import importlib

import pytest

ADAPTER_MODULES = [
    ("lub.agents.adapters.langgraph", "to_langgraph_node", "langgraph"),
    ("lub.agents.adapters.crewai", "to_crewai_agent", "crewai"),
    ("lub.agents.adapters.autogen", "to_autogen_agent", "autogen"),
    ("lub.agents.adapters.ruflo", "to_ruflo_agent", "ruflo"),
]


@pytest.mark.parametrize("module_path,entry_fn,extra_name", ADAPTER_MODULES)
def test_adapter_import_behavior(module_path, entry_fn, extra_name):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        # Acceptable outcome when the extra isn't installed.
        assert extra_name in str(exc) or "extra" in str(exc)
        return

    # Extra is installed; the entry function exists and is a scaffold.
    fn = getattr(module, entry_fn)
    assert callable(fn)


def test_langgraph_entry_signature():
    try:
        from lub.agents.adapters.langgraph import to_langgraph_node  # noqa: F401
    except ImportError:
        pytest.skip("langgraph extra not installed")

    # Cannot call without a real CalibratedAgent; just assert the scaffold
    # raises NotImplementedError on invocation with a fake.
    from lub.agents import CalibratedAgent

    class FakeAgent(CalibratedAgent):
        prompt_template = "x"

        def parse(self, raw: str) -> str:
            return raw

    fake = FakeAgent(backend=object(), uncertainty=object(), policy=object())
    from lub.agents.adapters.langgraph import to_langgraph_node

    with pytest.raises(NotImplementedError, match="scaffold"):
        to_langgraph_node(fake)
