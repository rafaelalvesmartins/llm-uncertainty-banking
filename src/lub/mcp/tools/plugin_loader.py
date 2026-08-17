# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Discover orchestrator-style plugins from a directory at server-build time.

The plugin layout convention (lifted originally from ruflo, now generic):

    <plugins_dir>/
      <plugin-name>/
        manifest.json    -- one of the supported formats (see below)
        handlers.py      -- module with HANDLERS = {"tool_name": fn, ...}

The manifest's ``format`` field selects the adapter used to translate it
into :class:`lub.mcp.server.ToolDef` records. When ``format`` is omitted
the legacy "ruflo" format is assumed for back-compat with manifests that
predate the dispatch table.

Supported formats (all in :data:`PLUGIN_FORMAT_ADAPTERS` below):

* ``"ruflo-v3"`` (alias: ``None`` for legacy manifests, also matches
  manifests whose ``name`` is ``@claude-flow/...``) -- the original
  ruvnet/ruflo plugin shape.

Future adapters (langgraph-pack, crewai-pack, autogen-pack) plug in the
same way: register them via :func:`register_plugin_format`. The loader
itself stays orchestrator-agnostic.

The default plugins directory resolves in this order (first hit wins):

1. ``$LUB_PLUGINS_DIR`` environment variable, if set.
2. ``~/.lub/plugins/`` if it exists.
3. ``./plugins/`` (cwd-relative) if it exists.

Returns an empty list quietly when no plugins are discovered -- this
keeps the lub MCP server cheap and zero-config for users who don't
ship orchestrator plugins.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from lub.mcp.tools.ruflo_compat import adapt_ruflo_manifest

if TYPE_CHECKING:
    from lub.mcp.server import ToolDef


_LOG = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Format-dispatch table
# ---------------------------------------------------------------------------

# A plugin-format adapter takes (manifest_dict, handlers_dict) and returns
# a list of ToolDef. The signature is intentionally minimal so future
# adapters (langgraph, crewai, autogen, custom) plug in without subclassing.
PluginAdapter = Callable[[dict[str, Any], dict[str, Any]], "list[ToolDef]"]

# Built-in format -> adapter table. Treat as read-only outside this module;
# use :func:`register_plugin_format` to extend.
PLUGIN_FORMAT_ADAPTERS: dict[str | None, PluginAdapter] = {
    "ruflo-v3": adapt_ruflo_manifest,
    "ruflo": adapt_ruflo_manifest,  # legacy short alias
    None: adapt_ruflo_manifest,  # missing format -> ruflo for back-compat
}


def register_plugin_format(name: str, adapter: PluginAdapter) -> None:
    """Register a new plugin-format adapter.

    Args:
        name: Format identifier the manifest's ``"format"`` field must
            match. Case-sensitive. Conventional names look like
            ``"langgraph-v1"``, ``"crewai-v1"``, etc.
        adapter: Callable ``(manifest, handlers) -> list[ToolDef]``.

    Calling ``register_plugin_format`` more than once with the same
    ``name`` overrides the prior adapter (intentional -- lets a vendored
    plugin pack override a built-in adapter).
    """
    PLUGIN_FORMAT_ADAPTERS[name] = adapter


def _resolve_plugins_dir() -> Path | None:
    env = os.environ.get("LUB_PLUGINS_DIR")
    if env:
        path = Path(env).expanduser()
        return path if path.is_dir() else None
    home = Path.home() / ".lub" / "plugins"
    if home.is_dir():
        return home
    cwd = Path.cwd() / "plugins"
    if cwd.is_dir():
        return cwd
    return None


def _load_handlers_module(handlers_path: Path) -> dict[str, Any]:
    """Import a plugin's ``handlers.py`` and return its ``HANDLERS`` dict."""
    spec = importlib.util.spec_from_file_location(
        f"_lub_plugin_{handlers_path.parent.name}", handlers_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load plugin handlers at {handlers_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    handlers = getattr(mod, "HANDLERS", None)
    if not isinstance(handlers, dict):
        raise AttributeError(
            f"plugin at {handlers_path.parent} must export "
            f"HANDLERS: dict[str, Callable] from handlers.py"
        )
    return handlers


def _select_adapter(manifest: dict[str, Any]) -> PluginAdapter:
    """Pick the right adapter for a manifest based on its ``format`` field."""
    fmt = manifest.get("format")
    if fmt in PLUGIN_FORMAT_ADAPTERS:
        return PLUGIN_FORMAT_ADAPTERS[fmt]
    # Heuristic fallback: a manifest with a name like ``@claude-flow/...``
    # is treated as ruflo-shaped even when ``format`` is missing.
    name = str(manifest.get("name", ""))
    if name.startswith(("@claude-flow/", "ruflo-")):
        return adapt_ruflo_manifest
    # Final fallback: legacy behavior (ruflo). Logged so a deployment
    # operator can see they may want to set ``format`` explicitly.
    _LOG.info(
        "plugin_loader.format.assumed_ruflo",
        plugin_name=name,
        known_formats=sorted(k for k in PLUGIN_FORMAT_ADAPTERS if k is not None),
    )
    return adapt_ruflo_manifest


def discover_plugins(
    plugins_dir: Path | str | None = None,
) -> list[ToolDef]:
    """Walk a plugins directory and adapt every manifest found.

    Format-agnostic: each manifest's ``format`` field selects the
    adapter from :data:`PLUGIN_FORMAT_ADAPTERS`. Plugin directories
    that mix formats (one banking-pack ruflo manifest + one
    langgraph-pack manifest) are handled correctly in a single pass.

    Args:
        plugins_dir: explicit directory to scan. When ``None`` the
            default resolution chain runs (env var, ``~/.lub/plugins``,
            ``./plugins``).

    Returns:
        Flat list of :class:`ToolDef` from every discovered plugin.
        Empty list when no directory or no plugins are found -- never
        raises on a missing directory, since "no plugins" is the
        default expectation for most lub deployments.
    """
    if plugins_dir is None:
        resolved = _resolve_plugins_dir()
        if resolved is None:
            return []
    else:
        resolved = Path(plugins_dir).expanduser()
        if not resolved.is_dir():
            _LOG.warning("plugin_loader.dir.missing", dir=str(resolved))
            return []

    out: list[ToolDef] = []
    for entry in sorted(resolved.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        handlers_path = entry / "handlers.py"
        if not manifest_path.is_file():
            continue
        if not handlers_path.is_file():
            _LOG.warning(
                "plugin_loader.handlers.missing",
                plugin=entry.name,
                expected=str(handlers_path),
            )
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            handlers = _load_handlers_module(handlers_path)
            adapter = _select_adapter(manifest)
            tools = adapter(manifest, handlers)
        except Exception as exc:
            _LOG.error(
                "plugin_loader.adapt.failed",
                plugin=entry.name,
                error=str(exc),
            )
            continue
        out.extend(tools)
        _LOG.info(
            "plugin_loader.adapted",
            plugin=entry.name,
            tool_count=len(tools),
        )
    return out


def discover_ruflo_plugins(
    plugins_dir: Path | str | None = None,
) -> list[ToolDef]:
    """Back-compat alias for :func:`discover_plugins`.

    Kept for callers that imported the ruflo-named function before the
    pass-32 generalization. New code should prefer
    :func:`discover_plugins`. Behavior is identical.
    """
    return discover_plugins(plugins_dir)


__all__ = [
    "PLUGIN_FORMAT_ADAPTERS",
    "PluginAdapter",
    "discover_plugins",
    "discover_ruflo_plugins",
    "register_plugin_format",
]
