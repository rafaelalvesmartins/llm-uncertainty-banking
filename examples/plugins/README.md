# examples/plugins/ — ruflo-style plugin demos for `lub.mcp`

Worked examples of the ruflo plugin convention that
[`lub.mcp.tools.plugin_loader.discover_ruflo_plugins`](../../src/lub/mcp/tools/plugin_loader.py)
auto-discovers at server-build time.

## Convention

Each plugin lives in its own subdirectory with two files:

```
<plugin_name>/
├── manifest.json    # ruflo manifest (name, version, tools list)
└── handlers.py      # Python module exporting HANDLERS dict
```

The `manifest.json` follows the `@claude-flow/plugin-*` shape used by
ruflo's official plugin registry:

```json
{
  "name": "@claude-flow/plugin-<short>",
  "version": "...",
  "description": "...",
  "tools": [
    {"name": "<tool>", "description": "...", "input_schema": {...}}
  ]
}
```

The `handlers.py` file must export a `HANDLERS` dict mapping every tool
name in the manifest to a callable of shape:

```python
def my_handler(args: dict[str, Any]) -> dict[str, Any]:
    ...
```

## Installing a plugin

Three ways to point `lub` at a plugin folder, in resolution order:

1. **Environment variable (best for CI / containers):**
   ```bash
   export LUB_PLUGINS_DIR=/path/to/plugins
   ```
2. **User home (best for local dev):**
   ```bash
   mkdir -p ~/.lub/plugins
   cp -r examples/plugins/banking_demo ~/.lub/plugins/
   ```
3. **Project-local (cwd-relative):**
   ```bash
   cp -r examples/plugins/banking_demo ./plugins/
   ```

Once installed, run `lub-mcp-server` (or call `build_server()` from
Python) and the plugin's tools appear in the catalog as:

```
ruflo.<plugin_short>.<tool_name>
```

For the included `banking_demo`:

- `ruflo.banking-demo.sr_11_7_check`
- `ruflo.banking-demo.regime_lookup`

The `@claude-flow/plugin-` prefix is stripped automatically when
constructing the namespace.

## Demos

| Folder | What it shows |
|---|---|
| [`banking_demo/`](banking_demo/) | Two stand-in tools — keyword-based SR 11-7 claim checker and a regime-name lookup. Stand-in for the future `lub-ruflo-banking-pack` which lands four real banking-compliance agents (`sr_11_7_auditor`, `basel_reporter`, `bcb_4658_mapper`, `ai_rmf_tagger`) post-launch. |

## Building your own

1. Copy `banking_demo/` to a new directory under your plugins folder.
2. Edit `manifest.json` — change the `name`, `version`, `description`,
   and the `tools` list.
3. Edit `handlers.py` — export a `HANDLERS` dict whose keys match
   every tool name in the manifest.
4. Restart `lub-mcp-server` (or rebuild via `build_server()`) and your
   tools appear in the catalog automatically.

For the full plugin contract see
[`src/lub/mcp/tools/ruflo_compat.py`](../../src/lub/mcp/tools/ruflo_compat.py)
and
[`src/lub/mcp/tools/plugin_loader.py`](../../src/lub/mcp/tools/plugin_loader.py).
