"""Tests for ``lub.agents.adapters.langgraph`` — v0.2 scaffold contract.

The adapter is a DEFER (v0.3) scaffold: both ``to_langgraph_node`` and
``LangGraphCompiler.build`` raise ``NotImplementedError``. These tests pin
the *contract of the stub*:

* the import-time guard for the missing ``langgraph`` extra,
* the public surface exposed via ``__all__``,
* that scaffold callables fail loudly with v0.3 pointers (not silently),
* that ``LangGraphCompiler`` stores its agents on construction.

When v0.3 lands and wires the real LangGraph node, these tests will need
to be extended with end-to-end pipeline cases (confidence-threshold
escalation, PII edge cases, backend timeout) — they are deliberately
out-of-scope for the scaffold revision.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util as importlib_util
import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _ensure_langgraph_importable() -> None:
    """Make the adapter importable even when ``langgraph`` is not installed.

    The adapter module raises ``ImportError`` at import time if
    ``importlib.util.find_spec('langgraph')`` returns ``None``. We inject a
    minimal stand-in so the rest of the test module can import the adapter
    once and exercise its scaffold behavior.
    """
    inserted = False
    if "langgraph" not in sys.modules:
        fake = types.ModuleType("langgraph")
        fake.__spec__ = importlib.machinery.ModuleSpec("langgraph", loader=None)
        sys.modules["langgraph"] = fake
        inserted = True

    # Drop any cached import so the guard re-runs against our stand-in.
    sys.modules.pop("lub.agents.adapters.langgraph", None)
    yield

    if inserted:
        sys.modules.pop("langgraph", None)
    sys.modules.pop("lub.agents.adapters.langgraph", None)


@pytest.fixture
def adapter():
    """Fresh import of the adapter module under test."""
    return importlib.import_module("lub.agents.adapters.langgraph")


@pytest.fixture
def mock_agent() -> MagicMock:
    """A stand-in :class:`CalibratedAgent` — no real LLM is invoked."""
    agent = MagicMock(name="CalibratedAgent")
    agent.run.return_value = MagicMock(
        output={"answer": "ok"},
        confidence=0.92,
        escalate=False,
    )
    return agent


# ---------------------------------------------------------------------------
# Import-time guard
# ---------------------------------------------------------------------------


class TestImportGuard:
    def test_module_imports_when_extra_is_available(self, adapter) -> None:
        assert hasattr(adapter, "to_langgraph_node")
        assert hasattr(adapter, "LangGraphCompiler")

    def test_raises_import_error_when_langgraph_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``langgraph`` is absent, importing the adapter must fail loud.

        Mirrors the user-facing ``pip install 'lub[langgraph]'`` hint that the
        guard surfaces.
        """
        original_find_spec = importlib_util.find_spec

        def fake_find_spec(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "langgraph":
                return None
            return original_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib_util, "find_spec", fake_find_spec)
        monkeypatch.delitem(sys.modules, "lub.agents.adapters.langgraph", raising=False)
        monkeypatch.delitem(sys.modules, "langgraph", raising=False)

        with pytest.raises(ImportError, match=r"lub\[langgraph\]"):
            importlib.import_module("lub.agents.adapters.langgraph")


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_all_lists_documented_entry_points(self, adapter) -> None:
        assert set(adapter.__all__) == {"to_langgraph_node", "LangGraphCompiler"}

    def test_to_langgraph_node_is_callable(self, adapter) -> None:
        assert callable(adapter.to_langgraph_node)

    def test_langgraph_compiler_is_a_class(self, adapter) -> None:
        assert isinstance(adapter.LangGraphCompiler, type)


# ---------------------------------------------------------------------------
# to_langgraph_node — scaffold contract
# ---------------------------------------------------------------------------


class TestToLangGraphNodeScaffold:
    def test_raises_not_implemented(self, adapter, mock_agent: MagicMock) -> None:
        with pytest.raises(NotImplementedError):
            adapter.to_langgraph_node(mock_agent)

    def test_error_message_pins_version_target(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        with pytest.raises(NotImplementedError) as exc:
            adapter.to_langgraph_node(mock_agent)
        assert "v0.3" in str(exc.value)

    def test_error_message_points_to_rfc(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        with pytest.raises(NotImplementedError) as exc:
            adapter.to_langgraph_node(mock_agent)
        assert "RFC_001" in str(exc.value)

    def test_error_message_points_to_agents_beta_extra(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        with pytest.raises(NotImplementedError) as exc:
            adapter.to_langgraph_node(mock_agent)
        assert "agents-beta" in str(exc.value)

    def test_does_not_invoke_agent_in_scaffold_mode(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        """The scaffold must fail before touching the agent — no silent calls,
        no partial side-effects on the wrapped CalibratedAgent."""
        with pytest.raises(NotImplementedError):
            adapter.to_langgraph_node(mock_agent)
        mock_agent.run.assert_not_called()
        mock_agent.assert_not_called()

    def test_accepts_custom_keys_without_swallowing_them(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        """Custom ``input_key`` / ``output_key`` / ``report_key`` must not
        suppress the scaffold's NotImplementedError."""
        with pytest.raises(NotImplementedError):
            adapter.to_langgraph_node(
                mock_agent,
                input_key="customer_query",
                output_key="agent_response",
                report_key="audit_trail",
            )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"input_key": ""},
            {"input_key": "x", "output_key": "y", "report_key": "z"},
        ],
    )
    def test_scaffold_is_stable_across_kwarg_shapes(
        self, adapter, mock_agent: MagicMock, kwargs: dict
    ) -> None:
        with pytest.raises(NotImplementedError):
            adapter.to_langgraph_node(mock_agent, **kwargs)


# ---------------------------------------------------------------------------
# LangGraphCompiler — scaffold contract
# ---------------------------------------------------------------------------


class TestLangGraphCompilerScaffold:
    def test_stores_single_agent(self, adapter, mock_agent: MagicMock) -> None:
        compiler = adapter.LangGraphCompiler(mock_agent)
        assert compiler.agents == (mock_agent,)

    def test_stores_multiple_agents_in_order(self, adapter) -> None:
        a, b, c = MagicMock(name="A"), MagicMock(name="B"), MagicMock(name="C")
        compiler = adapter.LangGraphCompiler(a, b, c)
        assert compiler.agents == (a, b, c)

    def test_accepts_zero_agents(self, adapter) -> None:
        """Empty construction is allowed — wiring (and any non-empty check)
        is deferred to v0.3."""
        compiler = adapter.LangGraphCompiler()
        assert compiler.agents == ()

    def test_build_raises_not_implemented(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        compiler = adapter.LangGraphCompiler(mock_agent)
        with pytest.raises(NotImplementedError) as exc:
            compiler.build()
        assert "v0.3" in str(exc.value)

    def test_build_points_to_agents_beta_extra(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        compiler = adapter.LangGraphCompiler(mock_agent)
        with pytest.raises(NotImplementedError) as exc:
            compiler.build()
        assert "agents-beta" in str(exc.value)

    def test_build_does_not_invoke_stored_agents(
        self, adapter, mock_agent: MagicMock
    ) -> None:
        compiler = adapter.LangGraphCompiler(mock_agent)
        with pytest.raises(NotImplementedError):
            compiler.build()
        mock_agent.run.assert_not_called()
        mock_agent.assert_not_called()


# ---------------------------------------------------------------------------
# Documentation / convention guards
# ---------------------------------------------------------------------------


class TestSourceConventions:
    """Lightweight checks that the scaffold keeps its declared conventions.

    The module's own docstring states that ``# TODO`` markers were retired in
    favor of ``DEFER (v0.3)``. If a future contributor accidentally re-adds
    a ``# TODO`` here, these tests catch it before merge.
    """

    def test_source_uses_defer_marker_not_todo(self, adapter) -> None:
        import ast
        import inspect

        source = inspect.getsource(adapter)
        assert "DEFER (v0.3)" in source

        # Check `# TODO` doesn't appear in actual code lines (excluding docstrings).
        tree = ast.parse(source)
        docstring_ranges = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                docstring_ranges.append((node.lineno, node.end_lineno))

        for i, line in enumerate(source.splitlines(), start=1):
            if any(start <= i <= end for start, end in docstring_ranges):
                continue
            assert "# TODO" not in line, f"Line {i}: {line}"
