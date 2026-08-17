# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""ruflo plugin manifest -> lub MCP ToolDef shim.

A ruflo plugin (per the ``@claude-flow/plugin-*`` convention used in
ruvnet/ruflo) ships a manifest of the shape::

    {
        "name": "@claude-flow/plugin-banking-compliance",
        "version": "0.1.0",
        "description": "...",
        "tools": [
            {"name": "sr_11_7_audit", "description": "...", "input_schema": {...}},
            ...
        ]
    }

This shim takes one such manifest plus a Python handler dict and emits
a list of :class:`lub.mcp.server.ToolDef` objects. The result drops
straight into ``lub.mcp.server.list_all_tools`` so a lub MCP server
can host ruflo plugins as first-class tools.

This is the v0.2 expression of the ``11_Ruflo_Synthesis.md`` thesis:
*lub provides the calibration layer beneath any orchestrator, ruflo
included.* For the v0.3 framework adapter
(``lub.agents.adapters.ruflo.to_ruflo_agent``) see RFC-001.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, create_model

__all__ = ["RufloPluginInput", "RufloPluginOutput", "adapt_ruflo_manifest"]

_LOG = structlog.get_logger(__name__)


class RufloPluginInput(BaseModel):
    """Generic input schema for a ruflo plugin tool.

    Plugins typically pass an arbitrary ``args`` dict whose actual
    contract is defined in the plugin's own ``input_schema``. We expose
    that as a free-form dict so the lub MCP server can forward without
    re-encoding.
    """

    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)


class RufloPluginOutput(BaseModel):
    """Generic output schema for a ruflo plugin tool."""

    model_config = ConfigDict(extra="forbid")

    plugin: str
    tool: str
    result: dict[str, Any] = Field(default_factory=dict)


def _make_handler(
    plugin_name: str,
    tool_name: str,
    impl: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _handle(payload: dict[str, Any]) -> dict[str, Any]:
        parsed = RufloPluginInput.model_validate(payload)
        try:
            result = impl(parsed.args)
        except Exception as exc:
            _LOG.warning("ruflo_plugin.error", plugin=plugin_name, tool=tool_name, error=str(exc))
            raise
        out = RufloPluginOutput(plugin=plugin_name, tool=tool_name, result=dict(result))
        return out.model_dump()

    return _handle


def adapt_ruflo_manifest(
    manifest: dict[str, Any],
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
) -> list[Any]:  # list[ToolDef] — Any avoids circular import at module load
    """Translate a ruflo plugin manifest into a list of lub MCP ToolDefs.

    Args:
        manifest: ruflo plugin manifest dict. Must contain ``name`` and
            a ``tools`` list. Each tool entry must contain ``name`` and
            ``description``; ``input_schema`` is optional.
        handlers: mapping of ``tool_name -> callable(args_dict) ->
            result_dict``. Every tool in the manifest must have a
            corresponding handler entry, or :class:`KeyError` is raised
            at adapt time (not at call time).

    Returns:
        One :class:`ToolDef` per manifest tool, named
        ``ruflo.<plugin_short>.<tool>`` to avoid collision with native
        lub MCP tools. ``plugin_short`` strips the ``@claude-flow/``
        prefix when present.
    """
    from lub.mcp.server import ToolDef

    plugin_name = str(manifest.get("name", "")).strip()
    if not plugin_name:
        raise ValueError("ruflo manifest missing 'name'")
    tools = manifest.get("tools", [])
    if not isinstance(tools, list):
        raise ValueError("ruflo manifest 'tools' must be a list")

    plugin_short = plugin_name.replace("@claude-flow/plugin-", "").replace("@claude-flow/", "")

    out: list[Any] = []
    for entry in tools:
        if not isinstance(entry, dict):
            raise ValueError(f"ruflo manifest tool entry not a dict: {entry!r}")
        tool_name = entry.get("name")
        if not tool_name or not isinstance(tool_name, str):
            raise ValueError(f"ruflo tool missing 'name': {entry!r}")
        if tool_name not in handlers:
            raise KeyError(
                f"ruflo plugin {plugin_name!r} declares tool {tool_name!r} "
                f"but no handler was supplied"
            )
        description = entry.get("description") or f"ruflo plugin tool {tool_name}"
        # Build per-tool input model from input_schema if provided, else
        # fall back to RufloPluginInput. We always wrap the output in
        # RufloPluginOutput for uniform observability across plugins.
        input_model = _input_model_from_schema(tool_name, entry.get("input_schema"))
        out.append(
            ToolDef(
                name=f"ruflo.{plugin_short}.{tool_name}",
                description=description,
                input_model=input_model,
                output_model=RufloPluginOutput,
                handler=_make_handler(plugin_name, tool_name, handlers[tool_name]),
            )
        )
    _LOG.info(
        "ruflo_compat.manifest.adapted",
        plugin=plugin_name,
        tool_count=len(out),
    )
    return out


def _input_model_from_schema(tool_name: str, schema: Any) -> type[BaseModel]:
    """Best-effort: build a pydantic model that mirrors a JSON schema."""
    if not isinstance(schema, dict):
        return RufloPluginInput

    # If the schema looks like a typical JSON-schema object, accept it
    # via the `args` passthrough. Full JSON-schema -> pydantic
    # translation is out of scope for v0.2; the passthrough preserves
    # validation semantics on the ruflo side without re-implementing
    # them on the lub side.
    fields: dict[str, Any] = {
        "args": (dict[str, Any], Field(default_factory=dict, description=str(schema)))  # type: ignore[arg-type]
    }
    model_name = f"RufloInput_{tool_name}".replace("-", "_").replace(".", "_")
    return create_model(
        model_name,
        __base__=BaseModel,
        **fields,
    )
