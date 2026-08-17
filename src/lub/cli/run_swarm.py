# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""``lub run-swarm`` — load an orchestrated pack and run it.

Per ADR-002 (and its pass-25 generalization to any orchestrator), the
recommended user-facing entry point for LUB is to build a calibrated
pack and hand it to an orchestration framework. This subcommand closes
the loop on the CLI side: instead of forcing users to write Python
``build_orchestrated_pack(...)`` calls, ``lub run-swarm`` accepts a
dotted path to a factory callable, materializes the pack, and either
runs it locally agent-by-agent or emits the ruflo JSON-RPC handshake
to stdout.

Examples
--------

Dry-run (just lists what would be registered)::

    lub run-swarm --pack mymodule:build_pack --dry-run

Run locally over a JSONL of prompts::

    lub run-swarm --pack mymodule:build_pack \\
        --inputs questions.jsonl --out results.jsonl

Emit the ruflo JSON-RPC handshake to stdout (pipe to claude-flow)::

    lub run-swarm --pack mymodule:build_pack --ruflo-handshake

The factory callable must take no arguments and return a list of
:class:`~lub.runtime.engine.OrchestratedAgentSpec` (or anything that
satisfies :class:`~lub.agents.adapters.orchestrator.OrchestratorAgentProtocol`).
"""

from __future__ import annotations

import contextlib
import importlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import structlog
import typer

from lub.cli import EXIT_INTERNAL, EXIT_USER, app
from lub.runtime import build_orchestrated_pack
from lub.runtime.engine import OrchestratedAgentSpec

__all__ = ["run_swarm"]

_LOG = structlog.get_logger("lub.cli.run_swarm")


def _load_factory(dotted_path: str) -> Any:
    """Resolve a ``module.sub:callable`` string into a Python callable."""
    if ":" not in dotted_path:
        raise typer.BadParameter(f"--pack must be 'module.path:factory_name', got {dotted_path!r}")
    module_path, attr_name = dotted_path.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise typer.BadParameter(f"could not import module {module_path!r}: {exc}") from exc
    try:
        factory = getattr(module, attr_name)
    except AttributeError as exc:
        raise typer.BadParameter(f"module {module_path!r} has no attribute {attr_name!r}") from exc
    if not callable(factory):
        raise typer.BadParameter(f"{dotted_path!r} is not callable")
    return factory


def _materialize(factory: Any) -> list[Any]:
    """Call the factory and normalize its output to a list of pack members."""
    raw = factory()
    if not isinstance(raw, Iterable):
        raise typer.BadParameter(
            f"factory must return an iterable of OrchestratedAgentSpec, got {type(raw).__name__}"
        )
    items = list(raw)
    if not items:
        raise typer.BadParameter("factory returned an empty pack")
    # If they handed us specs, materialize them; if they handed us
    # already-shaped agents, pass through.
    if all(isinstance(item, OrchestratedAgentSpec) for item in items):
        return build_orchestrated_pack(items)
    return items


def _emit_handshake(pack: list[Any]) -> dict[str, Any]:
    """Serialize the pack as a ruflo JSON-RPC handshake envelope.

    The shape mirrors the ``register_agents`` request the ruflo bridge
    in ``Visa_Genius/apps/api/src/visa_genius/orchestrator/ruflo_bridge.py``
    expects on stdin. Ruflo itself is not called here -- this just emits
    the message; the operator pipes it to ``claude-flow``.
    """
    return {
        "jsonrpc": "2.0",
        "method": "register_agents",
        "params": {
            "agents": [
                {
                    "name": getattr(member, "name", f"agent-{i}"),
                    "description": getattr(member, "description", None),
                    "metadata": dict(getattr(member, "metadata", {}) or {}),
                }
                for i, member in enumerate(pack)
            ],
        },
        "id": "lub-run-swarm",
    }


@app.command("run-swarm")
def run_swarm(
    pack: str = typer.Option(
        ...,
        "--pack",
        "-p",
        help="Dotted path to a zero-arg factory: 'module.path:factory_name'.",
    ),
    inputs: Path | None = typer.Option(
        None,
        "--inputs",
        "-i",
        exists=True,
        dir_okay=False,
        help='JSONL file; each line ``{"prompt": "..."}`` is fed to every member.',
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="JSONL output path. Defaults to stdout.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List members and exit without running.",
    ),
    ruflo_handshake: bool = typer.Option(
        False,
        "--ruflo-handshake",
        help="Emit ruflo JSON-RPC register_agents envelope to stdout and exit.",
    ),
) -> None:
    """Materialize an orchestrated pack and either inspect or run it."""
    try:
        factory = _load_factory(pack)
        members = _materialize(factory)
    except typer.BadParameter as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=EXIT_USER) from exc
    except (RuntimeError, ValueError, TypeError) as exc:
        _LOG.error("run_swarm.materialize_failed", error=str(exc))
        raise typer.Exit(code=EXIT_INTERNAL) from exc

    if dry_run:
        for i, m in enumerate(members):
            name = getattr(m, "name", f"agent-{i}")
            desc = getattr(m, "description", "") or ""
            typer.echo(f"  [{i}] {name}  -- {desc}")
        typer.echo(f"\n{len(members)} member(s) ready.")
        return

    if ruflo_handshake:
        envelope = _emit_handshake(members)
        typer.echo(json.dumps(envelope, indent=2))
        return

    if inputs is None:
        typer.echo(
            "error: provide --inputs (JSONL of prompts), --dry-run, or --ruflo-handshake",
            err=True,
        )
        raise typer.Exit(code=EXIT_USER)

    # ExitStack guarantees the sink is flushed/closed even on late SIGTERM
    # or any uncovered error path -- and makes the optional-open pattern
    # explicit rather than hand-rolled try/finally.
    with contextlib.ExitStack() as stack:
        sink = stack.enter_context(open(out, "w", encoding="utf-8")) if out else None
        for line_no, line in enumerate(inputs.read_text("utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                _LOG.warning("run_swarm.skip_bad_json", line=line_no, error=str(exc))
                continue
            prompt = payload.get("prompt") or payload.get("question") or ""
            if not prompt:
                continue
            for m in members:
                try:
                    result = m.run(prompt)  # OrchestratorAgentProtocol.run
                except (RuntimeError, ValueError, OSError) as exc:
                    _LOG.error(
                        "run_swarm.member_failed",
                        member=getattr(m, "name", "?"),
                        error=str(exc),
                    )
                    continue
                row = {
                    "line": line_no,
                    "agent": getattr(m, "name", "?"),
                    "prompt": prompt,
                    "result": result
                    if isinstance(result, (str, int, float, bool, dict, list))
                    else str(result),
                    "confidence": (getattr(m, "metadata", {}) or {}).get("last_confidence"),
                }
                serialized = json.dumps(row, ensure_ascii=False)
                if sink:
                    sink.write(serialized + "\n")
                else:
                    typer.echo(serialized)
