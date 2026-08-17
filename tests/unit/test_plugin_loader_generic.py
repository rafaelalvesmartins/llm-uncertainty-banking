# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for the generic plugin-format dispatch in lub.mcp.tools.plugin_loader.

Hermetic. Verifies:
  - Format-dispatch table picks the right adapter
  - Unknown formats fall back to ruflo (legacy behavior)
  - register_plugin_format() can add a new adapter
  - discover_ruflo_plugins back-compat alias still works
  - heuristic name-based detection (@claude-flow/...) routes to ruflo
"""

from __future__ import annotations

import json
from pathlib import Path

from lub.mcp.tools.plugin_loader import (
    PLUGIN_FORMAT_ADAPTERS,
    _select_adapter,
    discover_plugins,
    discover_ruflo_plugins,
    register_plugin_format,
)

# ---------------------------------------------------------------------------
# Format dispatch
# ---------------------------------------------------------------------------


def test_dispatch_table_has_ruflo_keys() -> None:
    assert "ruflo-v3" in PLUGIN_FORMAT_ADAPTERS
    assert "ruflo" in PLUGIN_FORMAT_ADAPTERS
    assert None in PLUGIN_FORMAT_ADAPTERS  # legacy fallback


def test_select_adapter_ruflo_v3() -> None:
    manifest = {"format": "ruflo-v3", "name": "test", "tools": []}
    adapter = _select_adapter(manifest)
    assert adapter is PLUGIN_FORMAT_ADAPTERS["ruflo-v3"]


def test_select_adapter_no_format_falls_back() -> None:
    """Manifest with no format field falls back to ruflo (legacy)."""
    manifest = {"name": "test", "tools": []}
    adapter = _select_adapter(manifest)
    assert adapter is PLUGIN_FORMAT_ADAPTERS[None]


def test_select_adapter_claude_flow_name_heuristic() -> None:
    """Manifest with @claude-flow/ name is detected as ruflo even without format."""
    manifest = {"name": "@claude-flow/plugin-banking", "tools": []}
    adapter = _select_adapter(manifest)
    assert adapter is PLUGIN_FORMAT_ADAPTERS[None]  # ruflo adapter


def test_select_adapter_unknown_format_logs_and_falls_back() -> None:
    """Unknown format string falls back to ruflo with a log entry (no crash)."""
    manifest = {"format": "totally-made-up-v7", "name": "test", "tools": []}
    adapter = _select_adapter(manifest)
    # Should still return the ruflo adapter (legacy behavior)
    assert adapter is PLUGIN_FORMAT_ADAPTERS[None]


# ---------------------------------------------------------------------------
# register_plugin_format extensibility
# ---------------------------------------------------------------------------


def test_register_plugin_format_adds_entry() -> None:
    def my_adapter(manifest, handlers):
        return ["fake-tool-def"]

    try:
        register_plugin_format("test-format-v1", my_adapter)
        assert PLUGIN_FORMAT_ADAPTERS["test-format-v1"] is my_adapter

        manifest = {"format": "test-format-v1", "name": "x"}
        adapter = _select_adapter(manifest)
        assert adapter is my_adapter
    finally:
        # Clean up so other tests aren't polluted
        PLUGIN_FORMAT_ADAPTERS.pop("test-format-v1", None)


def test_register_overrides_existing_format() -> None:
    """A second register_plugin_format call with the same name wins."""
    def adapter_a(m, h): return []
    def adapter_b(m, h): return []

    try:
        register_plugin_format("override-test", adapter_a)
        assert PLUGIN_FORMAT_ADAPTERS["override-test"] is adapter_a
        register_plugin_format("override-test", adapter_b)
        assert PLUGIN_FORMAT_ADAPTERS["override-test"] is adapter_b
    finally:
        PLUGIN_FORMAT_ADAPTERS.pop("override-test", None)


# ---------------------------------------------------------------------------
# discover_plugins / discover_ruflo_plugins
# ---------------------------------------------------------------------------


def test_discover_plugins_empty_dir_returns_empty(tmp_path: Path) -> None:
    result = discover_plugins(tmp_path)
    assert result == []


def test_discover_plugins_missing_dir_returns_empty(tmp_path: Path) -> None:
    """Pointing at a non-existent directory should not raise."""
    missing = tmp_path / "definitely-not-here"
    result = discover_plugins(missing)
    assert result == []


def test_discover_ruflo_plugins_alias_calls_discover_plugins(tmp_path: Path) -> None:
    """The back-compat alias must produce identical output."""
    a = discover_plugins(tmp_path)
    b = discover_ruflo_plugins(tmp_path)
    assert a == b == []


def test_discover_plugins_skips_non_directory_entries(tmp_path: Path) -> None:
    """Files at the plugins-root (not dirs) are ignored."""
    (tmp_path / "stray.txt").write_text("not a plugin")
    result = discover_plugins(tmp_path)
    assert result == []


def test_discover_plugins_skips_dir_without_manifest(tmp_path: Path) -> None:
    """A subdir without manifest.json is silently skipped."""
    (tmp_path / "incomplete").mkdir()
    result = discover_plugins(tmp_path)
    assert result == []


def test_discover_plugins_warns_on_missing_handlers(tmp_path: Path) -> None:
    """A subdir with manifest but no handlers.py is logged + skipped (not raised)."""
    plug = tmp_path / "no-handlers"
    plug.mkdir()
    (plug / "manifest.json").write_text(json.dumps({
        "format": "ruflo-v3",
        "name": "no-handlers",
        "tools": [],
    }))
    # No handlers.py
    result = discover_plugins(tmp_path)
    assert result == []  # skipped, not raised


# ---------------------------------------------------------------------------
# Format-mixed plugins directory
# ---------------------------------------------------------------------------


def test_discover_plugins_format_mix(tmp_path: Path) -> None:
    """A directory with TWO plugins, each declaring a different format,
    must dispatch each to the right adapter independently."""
    captured: list[tuple[str, str]] = []

    def custom_adapter_a(manifest, handlers):
        captured.append(("a", manifest["name"]))
        return []

    def custom_adapter_b(manifest, handlers):
        captured.append(("b", manifest["name"]))
        return []

    try:
        register_plugin_format("custom-a-v1", custom_adapter_a)
        register_plugin_format("custom-b-v1", custom_adapter_b)

        for name, fmt in [("alpha", "custom-a-v1"), ("beta", "custom-b-v1")]:
            plug = tmp_path / name
            plug.mkdir()
            (plug / "manifest.json").write_text(json.dumps({
                "format": fmt, "name": name, "tools": [],
            }))
            (plug / "handlers.py").write_text("HANDLERS = {}\n")

        discover_plugins(tmp_path)
        assert ("a", "alpha") in captured
        assert ("b", "beta") in captured
    finally:
        PLUGIN_FORMAT_ADAPTERS.pop("custom-a-v1", None)
        PLUGIN_FORMAT_ADAPTERS.pop("custom-b-v1", None)
