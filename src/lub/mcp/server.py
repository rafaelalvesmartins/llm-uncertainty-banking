# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""MCP server exposing LUB primitives as tools.

Tools:

* ``score_with_p_true``         — confidence via the P(True) estimator.
* ``score_with_token_sar``      — confidence via Sentence-SAR.
* ``reliability_diagram``       — replay calibration from the ledger.
* ``airmf_report``              — render an AI RMF assessment for a run.
* ``cascaded_answer``           — end-to-end cascaded-router call.

The actual ``mcp`` library is an optional dependency; if it is not
installed, importing this module still succeeds but :func:`build_server`
raises a clear error at call time. The tool *definitions* live here
so test code (and documentation generators) can introspect them
without the MCP runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Backend identifiers accepted by the auto-generated MCP tool surface.
#: Mirrors the keys in :data:`lub.wrappers.base._LAZY_REGISTRY`. When you
#: add a new backend, add it here too -- the Pydantic schema parses
#: this Literal so unknown values fail at request-parse time with a
#: clear error, not at runtime with a generic KeyError from
#: :func:`get_backend_cls`.
BackendName = Literal["dummy", "openai", "anthropic", "hf", "vllm"]


class ScoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1)
    backend: BackendName = "dummy"
    model: str = "dummy-model"


class ScoreOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    raw_scores: dict[str, float]


class ReliabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ledger_path: str
    method: str = "confidence"
    n_buckets: int = Field(default=10, ge=2, le=100)


class ReliabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buckets: list[dict[str, Any]]


class CascadedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    context: str = "regulatory-qa"


class CascadedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    confidence: float
    tier_used: str
    total_cost: float
    escalation_path: list[dict[str, Any]]


class AirmfInput(BaseModel):
    """Payload for :func:`_handle_airmf_report`.

    The caller supplies a minimal benchmark summary — the handler
    synthesises a :class:`~lub.types.BenchmarkResult` and renders it
    via :class:`~lub.reports.renderer.AIRMFReporter`. This keeps the
    MCP surface usable without requiring the full benchmark pipeline
    to have run in the same process.
    """

    model_config = ConfigDict(extra="forbid")
    backend: BackendName = "dummy"
    estimator: str = "token_logprob"
    dataset: str = "ad-hoc"
    dataset_version: str = ""
    n: int = Field(ge=0, default=0)
    accuracy: float = Field(ge=0.0, le=1.0, default=0.0)
    ece: float = Field(ge=0.0, le=1.0, default=0.0)
    refusal_auroc: float = Field(ge=0.0, le=1.0, default=0.5)
    metrics: dict[str, float] = Field(default_factory=dict)
    title: str | None = None
    format: str = Field(default="md", pattern="^(md|html)$")


class AirmfOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str
    body: str
    n_findings: int
    report_version: str = "1.0"


@dataclass(frozen=True)
class ToolDef:
    """Static definition of one MCP tool.

    We keep these as plain dataclasses so the rest of the code base can
    introspect them (for docs generation, help commands, smoke tests)
    without importing the optional ``mcp`` package.
    """

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_score_with_p_true(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.pipeline import UncertaintyPipeline

    args = ScoreInput.model_validate(payload)
    pipe = UncertaintyPipeline.from_pretrained(
        model=args.model, backend=args.backend, estimator="p_true"
    )
    result = pipe.answer(args.prompt)
    return ScoreOutput(
        answer=result.answer,
        confidence=float(result.confidence),
        raw_scores={k: float(v) for k, v in result.raw_scores.items()},
    ).model_dump()


def _handle_score_with_token_sar(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.pipeline import UncertaintyPipeline

    args = ScoreInput.model_validate(payload)
    pipe = UncertaintyPipeline.from_pretrained(
        model=args.model, backend=args.backend, estimator="sentence_sar"
    )
    result = pipe.answer(args.prompt)
    return ScoreOutput(
        answer=result.answer,
        confidence=float(result.confidence),
        raw_scores={k: float(v) for k, v in result.raw_scores.items()},
    ).model_dump()


def _handle_reliability_diagram(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.ledger import Ledger

    args = ReliabilityInput.model_validate(payload)
    with Ledger(args.ledger_path) as led:
        points = led.replay_calibration(method=args.method, n_buckets=args.n_buckets)
    return ReliabilityOutput(
        buckets=[
            {
                "bucket": p.bucket,
                "bucket_low": p.bucket_low,
                "bucket_high": p.bucket_high,
                "confidence_mean": p.confidence_mean,
                "accuracy": p.accuracy,
                "n": p.n,
            }
            for p in points
        ]
    ).model_dump()


def _handle_airmf_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Render an AI RMF report from a minimal benchmark summary.

    Synthesises a single-row :class:`~lub.types.BenchmarkResult` from
    the payload, wraps it in :class:`AIRMFReporter`, and returns the
    rendered markdown or HTML. Callers that already have real
    :class:`BenchmarkResult` records should use ``AIRMFReporter``
    directly from Python; this tool targets MCP clients that just
    have a metrics dict in hand.
    """
    import hashlib
    import sys as _sys
    from datetime import UTC, datetime

    from lub import __version__ as _lub_version
    from lub.reports.findings import FindingClassifier
    from lub.reports.renderer import AIRMFReporter
    from lub.types import BenchmarkResult

    args = AirmfInput.model_validate(payload)

    # Ensure the top-level typed fields also appear inside `metrics`
    # — the template reads both paths for backward compat.
    merged_metrics: dict[str, float] = {
        "accuracy": args.accuracy,
        "ece": args.ece,
        "refusal_auroc": args.refusal_auroc,
        **args.metrics,
    }
    seed_bytes = f"{args.backend}|{args.estimator}|{args.dataset}|{args.n}".encode()
    result = BenchmarkResult(
        repo_version=_lub_version,
        backend=args.backend,
        estimator=args.estimator,
        dataset=args.dataset,
        dataset_version=args.dataset_version,
        n=args.n,
        accuracy=args.accuracy,
        ece=args.ece,
        refusal_auroc=args.refusal_auroc,
        metrics=merged_metrics,
        timestamp=datetime.now(tz=UTC).isoformat(),
        python_version=_sys.version.split()[0],
        package_versions={"llm-uncertainty-banking": _lub_version},
        dataset_hash=hashlib.sha256(seed_bytes).hexdigest(),
    )
    reporter = AIRMFReporter(results=[result], title=args.title)
    body = reporter.render(format=args.format)  # type: ignore[arg-type]
    classifier = FindingClassifier()
    n_findings = len(classifier.classify(result).findings) if result.metrics else 0
    return AirmfOutput(
        format=args.format,
        body=body,
        n_findings=n_findings,
    ).model_dump()


def _handle_cascaded_answer(payload: dict[str, Any]) -> dict[str, Any]:
    from lub.governance.contexts import default_registry
    from lub.orchestration.router import Tier, TieredRouter
    from lub.pipeline import UncertaintyPipeline

    args = CascadedInput.model_validate(payload)
    ctx = default_registry().get(args.context)
    # For the MCP surface we default to the DummyBackend so the tool
    # is callable without credentials; production callers override.
    tiers: list[Tier] = []
    for i, name in enumerate(ctx.tier_order):
        pipe = UncertaintyPipeline.from_pretrained(
            model=f"dummy-{name}", backend="dummy", estimator="token_logprob"
        )
        tiers.append(Tier(name=name, pipeline=pipe, threshold=0.8 - 0.1 * i, cost=0.001 * (i + 1)))
    if not tiers:
        tiers = [
            Tier(
                name="default",
                pipeline=UncertaintyPipeline.from_pretrained(
                    model="dummy", backend="dummy", estimator="token_logprob"
                ),
                threshold=0.5,
                cost=0.0,
            )
        ]
    router = TieredRouter(tiers=tiers)
    routed = router.answer(args.prompt)
    return CascadedOutput(
        answer=routed.final.answer,
        confidence=float(routed.final.confidence),
        tier_used=routed.tier_used,
        total_cost=routed.total_cost,
        escalation_path=routed.escalation_path,
    ).model_dump()


TOOLS: list[ToolDef] = [
    ToolDef(
        name="score_with_p_true",
        description="Score (prompt, completion) using the P(True) estimator.",
        input_model=ScoreInput,
        output_model=ScoreOutput,
        handler=_handle_score_with_p_true,
    ),
    ToolDef(
        name="score_with_token_sar",
        description="Score (prompt, completion) using Sentence-SAR.",
        input_model=ScoreInput,
        output_model=ScoreOutput,
        handler=_handle_score_with_token_sar,
    ),
    ToolDef(
        name="reliability_diagram",
        description="Replay calibration from a ledger path and return reliability buckets.",
        input_model=ReliabilityInput,
        output_model=ReliabilityOutput,
        handler=_handle_reliability_diagram,
    ),
    ToolDef(
        name="airmf_report",
        description=(
            "Render an AI RMF markdown or HTML report for a benchmark "
            "summary (accuracy + ECE + refusal AUROC + any extra metrics)."
        ),
        input_model=AirmfInput,
        output_model=AirmfOutput,
        handler=_handle_airmf_report,
    ),
    ToolDef(
        name="cascaded_answer",
        description="Run the cascaded tiered router for a given bounded context.",
        input_model=CascadedInput,
        output_model=CascadedOutput,
        handler=_handle_cascaded_answer,
    ),
]


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def build_server() -> Any:
    """Instantiate the MCP server with every tool in :data:`TOOLS`.

    Raises
    ------
    ImportError:
        If the ``mcp`` package is not installed.
    """
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server  # noqa: F401 — re-exported from run_stdio
    except ImportError as exc:  # pragma: no cover — optional dep.
        raise ImportError(
            "The 'mcp' package is not installed. "
            "Install with: pip install 'llm-uncertainty-banking[mcp]'"
        ) from exc

    server: Any = Server("llm-uncertainty-banking")
    # Hand-written workflow tools first, then auto-generated estimator/metric
    # tools. Auto-discovery is deferred to server-build time so that
    # importing lub.mcp.server stays cheap (the estimator lazy-load
    # registry isn't walked just to introspect the tool catalog).
    from lub.mcp.tools import build_auto_tools

    for tool in TOOLS:
        _register(server, tool)
    for tool in build_auto_tools():
        _register(server, tool)
    return server


def list_all_tools() -> list[ToolDef]:
    """Return every tool — hand-written workflow tools + auto-generated.

    Cheap to call at any time (does walk the estimator registry, so it
    triggers the lazy-load imports). Useful for ``lub list mcp-tools``
    and for tests that want to verify the catalog without spinning up
    the actual MCP server runtime.
    """
    from lub.mcp.tools import build_auto_tools

    return [*TOOLS, *build_auto_tools()]


def _register(server: Any, tool: ToolDef) -> None:
    # Adapter binds the handler + pydantic models into the MCP server's
    # expected signature. Kept in a helper so each tool has a closure.
    def _call(arguments: dict[str, Any]) -> dict[str, Any]:
        return tool.handler(arguments)

    server.register_tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_model.model_json_schema(),
        handler=_call,
    )


def run_stdio() -> None:  # pragma: no cover - requires mcp runtime.
    """Entry point for the ``lub-mcp-server`` console script."""
    import asyncio

    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise ImportError(
            "The 'mcp' package is not installed. "
            "Install with: pip install 'llm-uncertainty-banking[mcp]'"
        ) from exc

    server = build_server()

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())


__all__ = [
    "TOOLS",
    "AirmfInput",
    "AirmfOutput",
    "CascadedInput",
    "CascadedOutput",
    "ReliabilityInput",
    "ReliabilityOutput",
    "ScoreInput",
    "ScoreOutput",
    "ToolDef",
    "build_server",
    "list_all_tools",
    "run_stdio",
]
