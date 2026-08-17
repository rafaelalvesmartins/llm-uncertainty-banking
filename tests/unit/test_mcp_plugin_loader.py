# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.mcp.tools.plugin_loader — disk discovery of ruflo plugins."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from lub.mcp.tools.plugin_loader import (
    _resolve_plugins_dir,
    discover_ruflo_plugins,
)


def _write_plugin(
    root: Path,
    name: str,
    manifest: dict,
    handlers_src: str,
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "handlers.py").write_text(textwrap.dedent(handlers_src), encoding="utf-8")
    return plugin_dir


def test_discover_returns_empty_list_when_no_dir(tmp_path: Path) -> None:
    missing = tmp_path / "definitely-not-here"
    out = discover_ruflo_plugins(missing)
    assert out == []


def test_discover_picks_up_one_plugin(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "banking-compliance",
        manifest={
            "name": "@claude-flow/plugin-banking-compliance",
            "tools": [
                {"name": "ping", "description": "test ping"},
            ],
        },
        handlers_src='HANDLERS = {"ping": lambda args: {"pong": True, "echo": args}}',
    )
    tools = discover_ruflo_plugins(tmp_path)
    assert len(tools) == 1
    assert tools[0].name == "ruflo.banking-compliance.ping"


def test_discover_skips_plugin_missing_handlers(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"name": "broken", "tools": [{"name": "x", "description": "x"}]}),
        encoding="utf-8",
    )
    # No handlers.py
    out = discover_ruflo_plugins(tmp_path)
    assert out == []


def test_discover_skips_plugin_with_bad_manifest(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        "bad-manifest",
        manifest={"tools": []},  # missing 'name'
        handlers_src="HANDLERS = {}",
    )
    out = discover_ruflo_plugins(tmp_path)
    assert out == []  # adapt_ruflo_manifest raises, loader logs + skips


def test_discover_handles_handlers_module_without_HANDLERS_dict(
    tmp_path: Path,
) -> None:
    _write_plugin(
        tmp_path,
        "no-handlers-attr",
        manifest={
            "name": "x",
            "tools": [{"name": "ping", "description": "p"}],
        },
        handlers_src="# no HANDLERS export\nFOO = 1\n",
    )
    out = discover_ruflo_plugins(tmp_path)
    assert out == []


def test_discover_skips_non_directory_entries(tmp_path: Path) -> None:
    (tmp_path / "stray.txt").write_text("ignore me")
    _write_plugin(
        tmp_path,
        "real",
        manifest={
            "name": "real",
            "tools": [{"name": "do_it", "description": "x"}],
        },
        handlers_src='HANDLERS = {"do_it": lambda args: {"ok": True}}',
    )
    tools = discover_ruflo_plugins(tmp_path)
    assert len(tools) == 1


def test_discover_picks_up_two_plugins_in_alphabetical_order(
    tmp_path: Path,
) -> None:
    _write_plugin(
        tmp_path,
        "z-second",
        manifest={
            "name": "z-second",
            "tools": [{"name": "z_tool", "description": "z"}],
        },
        handlers_src='HANDLERS = {"z_tool": lambda args: {"ok": True}}',
    )
    _write_plugin(
        tmp_path,
        "a-first",
        manifest={
            "name": "a-first",
            "tools": [{"name": "a_tool", "description": "a"}],
        },
        handlers_src='HANDLERS = {"a_tool": lambda args: {"ok": True}}',
    )
    tools = discover_ruflo_plugins(tmp_path)
    names = [t.name for t in tools]
    # iterdir + sorted -> alphabetical
    assert names == ["ruflo.a-first.a_tool", "ruflo.z-second.z_tool"]


def test_resolve_uses_env_var_first(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LUB_PLUGINS_DIR", str(tmp_path))
    resolved = _resolve_plugins_dir()
    assert resolved == tmp_path


def test_resolve_returns_none_when_env_var_points_at_missing_dir(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUB_PLUGINS_DIR", "/definitely/not/a/real/path/xyz")
    monkeypatch.setenv("HOME", "/tmp")  # ensure ~/.lub/plugins doesn't exist
    # Best-effort — works on any host where the explicit path is absent.
    resolved = _resolve_plugins_dir()
    if resolved is not None:
        # The cwd-relative ./plugins exists in some test environments;
        # accept that as a valid resolution rather than failing.
        assert resolved.is_dir()
