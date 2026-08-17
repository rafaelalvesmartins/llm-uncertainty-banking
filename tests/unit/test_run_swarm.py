# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Hermetic tests for ``lub.cli.run_swarm`` (the ``lub run-swarm`` subcommand).

The command shipped 2026-04-26 (pass 31) per ADR-002 -- it materializes
an orchestrated agent pack from a dotted-path factory and either lists,
emits a ruflo JSON-RPC handshake, or runs it locally. There were no
unit tests in ``tests/unit/`` for this surface; this file pins the
factory-resolution + materialization + handshake-shape contracts and
two CLI-level smoke paths so future refactors do not silently change
the dotted-path semantics.

Hermetic: no network, no real backend, no slow paths. Synthetic factory
modules are injected into ``sys.modules`` via ``monkeypatch.setitem``
so the test does not depend on test-discovery layout / pythonpath
quirks.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from lub.cli import app
from lub.cli.run_swarm import _emit_handshake, _load_factory, _materialize

runner = CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# Stub pack member -- minimal shape consumed by run_swarm helpers.
# ---------------------------------------------------------------------------


class _DummyMember:
    """Minimal pack member: ``.name`` + ``.run`` + optional ``.metadata``.

    ``run_swarm._materialize`` passes through any iterable whose items
    are not :class:`OrchestratedAgentSpec`; this class is the cheapest
    such shape and avoids pulling in :func:`build_orchestrated_pack`
    (which would require a full :class:`CalibratedAgent` tree).
    """

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self.metadata: dict[str, Any] = {}

    def run(self, input: Any) -> Any:  # noqa: A002 -- mirrors Protocol shape
        return f"echo:{input}"


def _install_fake_pack_module(monkeypatch: pytest.MonkeyPatch, factory) -> str:
    """Register a synthetic module exposing ``build_pack`` and return its dotted path."""
    mod_name = "_lub_test_run_swarm_fake_pack"
    fake_mod = types.ModuleType(mod_name)
    fake_mod.build_pack = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, mod_name, fake_mod)
    return f"{mod_name}:build_pack"


# ---------------------------------------------------------------------------
# _load_factory -- dotted-path resolution
# ---------------------------------------------------------------------------


def test_load_factory_rejects_path_without_colon() -> None:
    """``--pack`` must be ``module.path:factory_name``."""
    with pytest.raises(typer.BadParameter, match="module.path:factory_name"):
        _load_factory("no_colon_here")


def test_load_factory_rejects_missing_module() -> None:
    """An unimportable module surfaces as a BadParameter, not an ImportError."""
    with pytest.raises(typer.BadParameter, match="could not import module"):
        _load_factory("definitely_not_a_real_module_xyz_404:build_pack")


def test_load_factory_rejects_missing_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module exists but the attribute is absent -> BadParameter."""
    mod_name = "_lub_test_run_swarm_attr_missing"
    monkeypatch.setitem(sys.modules, mod_name, types.ModuleType(mod_name))
    with pytest.raises(typer.BadParameter, match="has no attribute"):
        _load_factory(f"{mod_name}:not_there")


def test_load_factory_rejects_non_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Attribute resolves but is not callable -> BadParameter."""
    mod_name = "_lub_test_run_swarm_not_callable"
    fake_mod = types.ModuleType(mod_name)
    fake_mod.build_pack = "I am a string, not a callable"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, mod_name, fake_mod)
    with pytest.raises(typer.BadParameter, match="not callable"):
        _load_factory(f"{mod_name}:build_pack")


def test_load_factory_returns_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: returns the factory callable so the caller can invoke it."""
    def factory() -> list:
        return [_DummyMember("alpha")]

    dotted = _install_fake_pack_module(monkeypatch, factory)
    resolved = _load_factory(dotted)
    assert resolved is factory


# ---------------------------------------------------------------------------
# _materialize -- factory-output normalization
# ---------------------------------------------------------------------------


def test_materialize_rejects_non_iterable() -> None:
    """A factory that returns a non-iterable surfaces as BadParameter."""
    with pytest.raises(typer.BadParameter, match="iterable"):
        _materialize(lambda: 42)


def test_materialize_rejects_empty_pack() -> None:
    """An empty iterable is rejected -- empty packs are never the user's intent."""
    with pytest.raises(typer.BadParameter, match="empty pack"):
        _materialize(lambda: [])


def test_materialize_passes_through_already_shaped_members() -> None:
    """If the factory hands back already-shaped agents, ``_materialize`` returns them as-is.

    This is the documented escape hatch for callers that already built a
    pack via :func:`lub.runtime.build_orchestrated_pack` upstream and just
    want ``run-swarm`` to drive it.
    """
    pack = _materialize(lambda: [_DummyMember("alpha"), _DummyMember("beta")])
    assert len(pack) == 2
    assert pack[0].name == "alpha"
    assert pack[1].name == "beta"


# ---------------------------------------------------------------------------
# _emit_handshake -- ruflo JSON-RPC envelope shape
# ---------------------------------------------------------------------------


def test_emit_handshake_envelope_shape() -> None:
    """The envelope mirrors what the ruflo bridge expects on stdin."""
    pack = [_DummyMember("alpha", "first"), _DummyMember("beta", "second")]
    pack[1].metadata["sla_p95_ms"] = 800
    envelope = _emit_handshake(pack)

    assert envelope["jsonrpc"] == "2.0"
    assert envelope["method"] == "register_agents"
    assert envelope["id"] == "lub-run-swarm"
    agents = envelope["params"]["agents"]
    assert [a["name"] for a in agents] == ["alpha", "beta"]
    assert agents[0]["description"] == "first"
    assert agents[1]["description"] == "second"
    # Metadata is propagated as a plain dict (JSON-serializable).
    assert agents[1]["metadata"] == {"sla_p95_ms": 800}
    assert agents[0]["metadata"] == {}


def test_emit_handshake_falls_back_when_member_lacks_name() -> None:
    """A member without ``.name`` gets an indexed fallback so the envelope stays valid."""

    class _Nameless:
        def run(self, x: Any) -> Any:
            return x

    envelope = _emit_handshake([_Nameless()])
    assert envelope["params"]["agents"][0]["name"] == "agent-0"


# ---------------------------------------------------------------------------
# CLI surface -- end-to-end via typer.testing.CliRunner.
# ---------------------------------------------------------------------------


def test_run_swarm_dry_run_lists_members(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--dry-run`` lists members and exits 0 without invoking ``.run``."""
    def factory() -> list:
        return [_DummyMember("alpha", "first"), _DummyMember("beta", "second")]

    dotted = _install_fake_pack_module(monkeypatch, factory)
    result = runner.invoke(app, ["run-swarm", "--pack", dotted, "--dry-run"])
    assert result.exit_code == 0, result.stderr
    assert "alpha" in result.stdout
    assert "beta" in result.stdout
    assert "2 member(s) ready" in result.stdout


def test_run_swarm_ruflo_handshake_emits_jsonrpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--ruflo-handshake`` emits a parsable JSON-RPC envelope to stdout."""
    def factory() -> list:
        return [_DummyMember("alpha"), _DummyMember("beta")]

    dotted = _install_fake_pack_module(monkeypatch, factory)
    result = runner.invoke(app, ["run-swarm", "--pack", dotted, "--ruflo-handshake"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["method"] == "register_agents"
    assert [a["name"] for a in payload["params"]["agents"]] == ["alpha", "beta"]


def test_run_swarm_without_inputs_or_flags_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``--inputs`` / ``--dry-run`` / ``--ruflo-handshake`` the CLI errors out."""
    def factory() -> list:
        return [_DummyMember("alpha")]

    dotted = _install_fake_pack_module(monkeypatch, factory)
    result = runner.invoke(app, ["run-swarm", "--pack", dotted])
    assert result.exit_code == 1
    assert "provide --inputs" in result.stderr


def test_run_swarm_bad_pack_path_errors() -> None:
    """A malformed ``--pack`` value exits with EXIT_USER (1)."""
    result = runner.invoke(app, ["run-swarm", "--pack", "missing_colon", "--dry-run"])
    assert result.exit_code == 1
    assert "module.path:factory_name" in result.stderr
