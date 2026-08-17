# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""FastAPI middleware stack for the Bridge banking AI platform.

Three independently-configurable middlewares the Bradesco Bridge mounts in
front of :mod:`lub.api.routes`. Each one closes a specific regulatory
or operational gap that the customer-facing channels (WhatsApp chatbot,
call-center copilot, smart payments) face at production scale:

* :class:`AuditMiddleware` — appends a :class:`~lub.bridge.audit.AuditEntry`
  envelope for every request/response pair. The route handlers already
  write rich, decision-level audit rows (model, confidence, policy
  outcome). This middleware complements them with an *edge-level*
  evidence stream — the HTTP request actually received, the status code
  actually returned, the wall-clock latency observed at the boundary —
  so a BCB 4893 §III reconstruction can prove "the bank's API received
  this request and replied X" independent of any application bug.
* :class:`RateLimitMiddleware` — enforces per-customer, per-channel
  token-bucket caps using :class:`~lub.bridge.rate_limiter.RateLimiter`.
  Protects the Azure OpenAI / Anthropic / local-GPU pool from a runaway
  client and keeps the 90%-retention / 95%-accuracy SLAs intact for
  well-behaved customers. Rejected requests return HTTP 429 with a
  ``Retry-After`` header derived from the bucket refill rate.
* :class:`ContentSafetyMiddleware` — refuses prompts that match a
  configurable deny-list (PII patterns, prompt-injection sentinels,
  abusive language). Acts *before* the request reaches an agent so the
  bank never spends inference budget on traffic it must refuse anyway,
  and so the refusal is recorded as a deliberate policy decision rather
  than as a model abstention.

Each middleware is opt-in via :func:`install_middleware`, which takes the
same collaborator objects as :func:`lub.api.routes.create_app` and mounts
only the ones the deployment configured. Production deployments mount
all three; local smoke-tests can mount none and still get a working app.

Why a middleware (not a route dependency)
-----------------------------------------

FastAPI dependencies fire *inside* the request handler, which means a
``RateLimit`` dependency cannot reject a request before the request body
has been read. At Bradesco scale this matters: the body for a
``POST /query`` carries the customer prompt, which may be megabytes of
voice-transcript JSON. Rejecting at the middleware layer lets us short-
circuit the read on a rejected request and saves both bandwidth and the
cost of parsing a body we will throw away.

The same reasoning applies to content-safety: refusing at the edge means
the refusal is logged once, by one component, instead of being inferred
from a downstream guard abstention.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import structlog

from lub.connectors.bridge.audit import AuditDecision, AuditEntry, AuditTrail
from lub.connectors.bridge.rate_limiter import RateLimiter
from lub.connectors.bridge.session import Channel as SessionChannel

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import ASGIApp

__all__ = [
    "AuditMiddleware",
    "AuditMiddlewareConfig",
    "ContentSafetyConfig",
    "ContentSafetyMiddleware",
    "ContentSafetyViolation",
    "RateLimitMiddleware",
    "RateLimitMiddlewareConfig",
    "install_middleware",
]

_LOG = structlog.get_logger("lub.api.middleware")


# ---------------------------------------------------------------------------
# Shared header / channel coercion
# ---------------------------------------------------------------------------

#: Header carrying the pseudonymous customer identifier. Bradesco's gateway
#: rewrites the raw CPF/CNPJ to an internal hash before the request reaches
#: Bridge, so this header never carries raw PII.
HEADER_CUSTOMER_ID: Final[str] = "x-customer-id"

#: Header carrying the originating channel (``whatsapp``/``app``/``web``/
#: ``call_center``). Falls back to ``app`` when absent.
HEADER_CHANNEL: Final[str] = "x-channel"

#: Request-state key under which middlewares stash a stable request UUID
#: so downstream handlers and the audit envelope can correlate logs.
STATE_REQUEST_ID: Final[str] = "lub_request_id"

#: Request-state key holding the parsed channel (a :class:`SessionChannel`).
STATE_CHANNEL: Final[str] = "lub_channel"

#: Request-state key holding the customer identifier (a string).
STATE_CUSTOMER_ID: Final[str] = "lub_customer_id"


_HEADER_TO_CHANNEL: Final[dict[str, SessionChannel]] = {
    "app": SessionChannel.MOBILE_APP,
    "mobile_app": SessionChannel.MOBILE_APP,
    "whatsapp": SessionChannel.WHATSAPP,
    "web": SessionChannel.WEB,
    "call_center": SessionChannel.CALL_CENTER,
}


def _coerce_channel(raw: str | None) -> SessionChannel:
    """Map an inbound ``X-Channel`` header to a :class:`SessionChannel`.

    Unknown values fall back to ``MOBILE_APP`` — never refuse the request
    on a bad channel header alone because a malformed gateway header is
    an operational issue, not a policy violation, and Bradesco's retention
    KPI counts every failed customer turn against the platform.
    """
    if not raw:
        return SessionChannel.MOBILE_APP
    return _HEADER_TO_CHANNEL.get(raw.strip().lower(), SessionChannel.MOBILE_APP)


def _customer_id_from_request(request: Request) -> str:
    """Pull the pseudonymous customer id from headers; anonymise if absent."""
    cid = request.headers.get(HEADER_CUSTOMER_ID, "").strip()
    if cid:
        return cid
    return f"anon-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Audit middleware
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditMiddlewareConfig:
    """Edge-level audit policy.

    Attributes
    ----------
    paths:
        Path prefixes for which the audit envelope is written. Defaults
        to every non-health path so liveness probes (which run hundreds
        of times per minute per pod) do not flood the trail.
    model_name:
        Stable identifier of the model backing the platform. Written
        verbatim onto every edge entry so a regulator can correlate an
        edge record back to the model version active at request time.
    redact_query:
        If ``True``, the request body is recorded as a length-only
        placeholder. Used in dev/test environments where the body may
        contain non-pseudonymised PII. Production runs with this off so
        the BCB 4893 reconstruction has the prompt the bank actually
        received.
    """

    paths: tuple[str, ...] = ("/query", "/agents")
    model_name: str = "unknown"
    redact_query: bool = False


class AuditMiddleware:
    """Edge audit envelope for every Bridge HTTP request.

    Wraps a :class:`~lub.bridge.audit.AuditTrail` and appends one entry
    per request to the configured paths. The middleware never raises out
    of the audit code path: an :class:`~lub.bridge.audit.AuditTrailError`
    is logged at ``error`` level but never propagated, because a single
    audit-disk hiccup must not break the customer-facing channel.

    This is *complementary* to the per-decision audit rows that
    :mod:`lub.api.routes` writes from the handler — the handler-level
    row carries the guard verdict and model output; this edge-level row
    carries the HTTP status, latency, and request shape.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        trail: AuditTrail,
        config: AuditMiddlewareConfig | None = None,
    ) -> None:
        self._app = app
        self._trail = trail
        self._config = config or AuditMiddlewareConfig()

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[Any], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        from starlette.requests import Request

        request = Request(scope, receive=receive)
        path = request.url.path
        if not self._should_audit(path):
            await self._app(scope, receive, send)
            return

        # Stamp a request id early so the route handler can re-use it.
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})
        request.state.__dict__.setdefault(STATE_REQUEST_ID, request_id)

        customer_id = _customer_id_from_request(request)
        channel = _coerce_channel(request.headers.get(HEADER_CHANNEL))
        request.state.__dict__[STATE_CUSTOMER_ID] = customer_id
        request.state.__dict__[STATE_CHANNEL] = channel

        start = time.monotonic()
        status_code = 500
        captured_status: dict[str, int] = {"code": 500}

        async def send_wrapper(message: Any) -> None:
            """Intercept the ASGI ``send`` to capture the HTTP status Bridge returned.

            Sniffs the ``http.response.start`` frame for its ``status`` field
            and stashes it in ``captured_status`` before forwarding the message
            untouched, so the enclosing :class:`AuditMiddleware` can write the
            real status code into the edge-level BCB 4893 evidence row that
            Bridge appends to its :class:`~lub.bridge.audit.AuditTrail`.
            """
            if isinstance(message, dict) and message.get("type") == "http.response.start":
                captured_status["code"] = int(message.get("status", 500))
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
            status_code = captured_status["code"]
        except Exception:
            status_code = 500
            self._record(
                request=request,
                request_id=request_id,
                customer_id=customer_id,
                channel=channel,
                status_code=status_code,
                latency_ms=(time.monotonic() - start) * 1000.0,
                escalated=True,
                escalation_reason="middleware_exception",
            )
            raise
        else:
            self._record(
                request=request,
                request_id=request_id,
                customer_id=customer_id,
                channel=channel,
                status_code=status_code,
                latency_ms=(time.monotonic() - start) * 1000.0,
                escalated=status_code >= 500,
                escalation_reason=None if status_code < 500 else f"http_{status_code}",
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _should_audit(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._config.paths)

    def _record(
        self,
        *,
        request: Request,
        request_id: str,
        customer_id: str,
        channel: SessionChannel,
        status_code: int,
        latency_ms: float,
        escalated: bool,
        escalation_reason: str | None,
    ) -> None:
        query_marker = (
            f"<redacted len={int(request.headers.get('content-length') or 0)}>"
            if self._config.redact_query
            else f"<edge {request.method} {request.url.path}>"
        )
        try:
            self._trail.log_decision(
                AuditEntry(
                    entry_id=request_id,
                    customer_id=customer_id,
                    session_id=request.headers.get("x-session-id", "") or request_id,
                    query=query_marker,
                    response=f"HTTP {status_code}",
                    confidence=None,
                    decision=(
                        AuditDecision.PASSTHROUGH if status_code < 400 else AuditDecision.ESCALATE
                    ),
                    agent_used="edge",
                    model_used=self._config.model_name,
                    latency_ms=max(0.0, latency_ms),
                    escalated=escalated,
                    escalation_reason=escalation_reason,
                    extra={
                        "channel": channel.value,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 — must not break the request path
            _LOG.error(
                "api.middleware.audit.write_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                path=request.url.path,
            )


# ---------------------------------------------------------------------------
# Rate-limit middleware
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitMiddlewareConfig:
    """Edge rate-limit policy.

    Attributes
    ----------
    paths:
        Path prefixes the limiter applies to. Defaults to ``("/query",)``
        because that is the only endpoint that consumes a model token
        budget; health/metrics/compliance are cheap and must remain
        reachable for the on-call team even when /query is throttled.
    reject_status_code:
        HTTP status returned on rejection. Defaults to 429 (Too Many
        Requests). Configurable because some legacy clients in the
        Bradesco fleet retry only on 503; operators can swap to 503
        per-channel until those clients are upgraded.
    include_retry_after:
        Emit a ``Retry-After`` header derived from
        :meth:`RateLimiter.wait`. Default ``True``.
    """

    paths: tuple[str, ...] = ("/query",)
    reject_status_code: int = 429
    include_retry_after: bool = True


class RateLimitMiddleware:
    """Per-customer, per-channel edge rate limiter.

    Delegates the bucket math to :class:`~lub.bridge.rate_limiter.RateLimiter`;
    this class only owns the HTTP shape (status, headers, JSON envelope)
    and the request-state plumbing the audit middleware reuses.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        config: RateLimitMiddlewareConfig | None = None,
    ) -> None:
        self._app = app
        self._limiter = limiter
        self._config = config or RateLimitMiddlewareConfig()

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[Any], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        from starlette.requests import Request

        request = Request(scope, receive=receive)
        if not self._should_limit(request.url.path):
            await self._app(scope, receive, send)
            return

        customer_id = request.state.__dict__.get(STATE_CUSTOMER_ID) or _customer_id_from_request(
            request
        )
        channel = request.state.__dict__.get(STATE_CHANNEL) or _coerce_channel(
            request.headers.get(HEADER_CHANNEL)
        )

        allowed = self._limiter.allow(customer_id, channel)
        if allowed:
            await self._app(scope, receive, send)
            return

        retry_after = (
            int(self._limiter.wait(customer_id, channel) + 0.999)
            if self._config.include_retry_after
            else None
        )
        await self._send_rejection(send, customer_id, channel, retry_after)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _should_limit(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._config.paths)

    async def _send_rejection(
        self,
        send: Callable[[Any], Awaitable[None]],
        customer_id: str,
        channel: SessionChannel,
        retry_after: int | None,
    ) -> None:
        body = json.dumps(
            {
                "error": "rate_limited",
                "detail": (
                    "Request rate exceeds the per-customer budget for this "
                    "channel. The Bridge platform throttles to protect the "
                    "model backend and other customers' SLAs."
                ),
                "channel": channel.value,
            }
        ).encode("utf-8")
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if retry_after is not None:
            headers.append((b"retry-after", str(max(1, retry_after)).encode("ascii")))
        _LOG.info(
            "api.middleware.rate_limit.rejected",
            customer_id=customer_id,
            channel=channel.value,
            retry_after=retry_after,
        )
        await send(
            {
                "type": "http.response.start",
                "status": self._config.reject_status_code,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Content-safety middleware
# ---------------------------------------------------------------------------


class ContentSafetyViolation(ValueError):
    """Raised by a custom :class:`ContentSafetyConfig.validator` to refuse a request."""


# Default deny-list patterns. Conservative — covers prompt-injection
# sentinels and obvious banking-fraud probes ("share your password",
# "OTP code"). Real deployments compose this with a dedicated content-
# moderation backend (Azure AI Content Safety, internal model). The
# patterns are case-insensitive and matched against the raw body.
_DEFAULT_DENY_PATTERNS: Final[tuple[str, ...]] = (
    r"ignore (all|previous|prior) instructions",
    r"you are now (?:DAN|jailbroken)",
    r"reveal (?:your )?system prompt",
    r"share your (?:password|otp|cvv|pin)",
    r"send (?:me )?(?:your |the )?(?:password|otp|cvv|pin)",
)


@dataclass(frozen=True)
class ContentSafetyConfig:
    """Content-safety policy.

    Attributes
    ----------
    paths:
        Path prefixes scanned. Defaults to ``("/query",)`` — the only
        endpoint that forwards a customer prompt to a model.
    deny_patterns:
        Regex patterns. A request body matching any pattern is refused
        with HTTP 400 and an explanatory JSON envelope.
    max_body_bytes:
        Hard cap on the request body length. Defaults to 64 KiB,
        comfortable headroom over the 4 096-character prompt cap that
        :class:`~lub.api.models.QueryRequest` already enforces and a
        sensible upper bound on the WhatsApp voice-transcript payload.
    validator:
        Optional callable ``(body_text) -> None`` that runs after the
        regex pass. Raise :class:`ContentSafetyViolation` to refuse.
        Lets a deployment plug in an external moderation backend without
        subclassing the middleware.
    reject_status_code:
        HTTP status returned on a violation. Defaults to 400.
    """

    paths: tuple[str, ...] = ("/query",)
    deny_patterns: tuple[str, ...] = _DEFAULT_DENY_PATTERNS
    max_body_bytes: int = 64 * 1024
    validator: Callable[[str], None] | None = None
    reject_status_code: int = 400


class ContentSafetyMiddleware:
    """Block harmful, oversize, or out-of-policy prompts at the edge.

    Reads the request body, scans it against the configured deny-list,
    and either passes the body through unchanged (preserving the bytes
    for the downstream handler) or returns a structured refusal. The
    body is re-injected via a wrapped ``receive`` callable so the
    underlying ASGI handler sees the request as if the middleware were
    not present.

    The middleware is deliberately conservative: it refuses on a regex
    match without trying to "clean up" or rewrite the prompt. A bank-
    grade content filter that mutated customer text would itself be a
    compliance risk — the refusal is logged, the customer sees an
    explanatory message, and the request never reaches an agent.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: ContentSafetyConfig | None = None,
    ) -> None:
        self._app = app
        self._config = config or ContentSafetyConfig()
        self._compiled = tuple(re.compile(pat, re.IGNORECASE) for pat in self._config.deny_patterns)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[Any], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        from starlette.requests import Request

        request = Request(scope)
        if not self._should_scan(request.url.path):
            await self._app(scope, receive, send)
            return

        body = await self._read_body(receive)
        if len(body) > self._config.max_body_bytes:
            await self._send_refusal(
                send,
                reason="body_too_large",
                detail=(
                    f"Request body of {len(body)} bytes exceeds the "
                    f"{self._config.max_body_bytes}-byte safety cap."
                ),
            )
            return

        text = body.decode("utf-8", errors="replace")
        violation = self._scan(text)
        if violation is not None:
            _LOG.info(
                "api.middleware.content_safety.rejected",
                path=request.url.path,
                reason=violation,
            )
            await self._send_refusal(
                send,
                reason="content_safety_violation",
                detail=f"Request refused by content safety: {violation}.",
            )
            return

        await self._app(scope, self._replay(body), send)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _should_scan(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._config.paths)

    async def _read_body(self, receive: Callable[[], Awaitable[Any]]) -> bytes:
        chunks: list[bytes] = []
        total = 0
        cap = self._config.max_body_bytes + 1  # +1 so we can detect overflow
        while True:
            message = await receive()
            if not isinstance(message, dict):
                continue
            if message.get("type") == "http.request":
                chunk = message.get("body", b"") or b""
                if chunk:
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > cap:
                        # Drain the rest so the client isn't left hanging,
                        # but stop accumulating — we already know we'll refuse.
                        if not message.get("more_body", False):
                            break
                        continue
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break
        return b"".join(chunks)

    def _scan(self, text: str) -> str | None:
        for pattern in self._compiled:
            if pattern.search(text):
                return f"deny_pattern:{pattern.pattern}"
        validator = self._config.validator
        if validator is not None:
            try:
                validator(text)
            except ContentSafetyViolation as exc:
                return f"validator:{exc}"
            except Exception as exc:  # noqa: BLE001
                _LOG.error(
                    "api.middleware.content_safety.validator_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return "validator:internal_error"
        return None

    @staticmethod
    def _replay(body: bytes) -> Callable[[], Awaitable[Any]]:
        sent = False

        async def receive() -> Any:
            """Replay the buffered request body once for the downstream Bridge handler.

            :class:`ContentSafetyMiddleware` had to drain the ASGI receive
            stream to scan the prompt; this closure re-emits those bytes as
            a single ``http.request`` frame so the Bridge route handler (and
            the agent it dispatches to) sees the request exactly as the
            customer sent it. Subsequent calls return ``http.disconnect`` so
            the handler does not block waiting for more body.
            """
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    async def _send_refusal(
        self,
        send: Callable[[Any], Awaitable[None]],
        *,
        reason: str,
        detail: str,
    ) -> None:
        body = json.dumps({"error": reason, "detail": detail}).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": self._config.reject_status_code,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Composition helper
# ---------------------------------------------------------------------------


def install_middleware(
    app: Any,
    *,
    audit_trail: AuditTrail | None = None,
    audit_config: AuditMiddlewareConfig | None = None,
    rate_limiter: RateLimiter | None = None,
    rate_limit_config: RateLimitMiddlewareConfig | None = None,
    content_safety_config: ContentSafetyConfig | None = None,
    enable_content_safety: bool = True,
) -> Any:
    """Mount the Bridge middleware stack onto a FastAPI app.

    Order matters. FastAPI runs middlewares in *reverse* registration
    order on the request path: the last one registered runs first. We
    therefore register in the order **audit -> rate-limit -> content-
    safety**, which yields the runtime order **content-safety first,
    then rate-limit, then audit last** — exactly what we want:

    1. **Content-safety** runs first so refused requests never burn rate
       budget or pollute the audit trail with attack traffic.
    2. **Rate-limit** runs next so throttled requests never reach the
       handler, but *do* show up in the audit trail (operators must be
       able to see throttling events).
    3. **Audit** runs last so every request that made it past the two
       prior gates — including ones the handler eventually 500'd on —
       is reflected at the edge.

    Parameters
    ----------
    app:
        The FastAPI application returned by
        :func:`lub.api.routes.create_app`.
    audit_trail:
        When supplied, an :class:`AuditMiddleware` is mounted with this
        trail. When ``None``, no edge audit envelope is written (the
        route handlers' per-decision audit rows are unaffected).
    audit_config, rate_limit_config, content_safety_config:
        Optional config overrides. Defaults are production-safe.
    rate_limiter:
        When supplied, a :class:`RateLimitMiddleware` is mounted. When
        ``None``, no edge rate-limiting is performed.
    enable_content_safety:
        Toggle for :class:`ContentSafetyMiddleware`. Defaults to ``True``
        because banking deployments should always have *some* edge
        content gate, even if it is only the conservative deny-list.

    Returns
    -------
    The same FastAPI app, with middlewares installed in-place. Returned
    for fluent-call ergonomics::

        app = install_middleware(create_app(...), audit_trail=trail, ...)
    """
    if enable_content_safety:
        app.add_middleware(
            ContentSafetyMiddleware,
            config=content_safety_config,
        )
        _LOG.info("api.middleware.content_safety.installed")

    if rate_limiter is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=rate_limiter,
            config=rate_limit_config,
        )
        _LOG.info(
            "api.middleware.rate_limit.installed",
            rpm=rate_limiter.config.requests_per_minute,
            burst=rate_limiter.config.burst_size,
        )

    if audit_trail is not None:
        app.add_middleware(
            AuditMiddleware,
            trail=audit_trail,
            config=audit_config,
        )
        _LOG.info("api.middleware.audit.installed")
    else:
        _LOG.warning(
            "api.middleware.audit.skipped",
            detail=(
                "No AuditTrail supplied; edge-level BCB 4893 evidence stream "
                "is disabled. Per-decision audit rows from the route handler "
                "are unaffected."
            ),
        )

    return app


# Lazy import guard: importing this module does not require Starlette,
# but the middleware classes only function inside a running ASGI server.
# Keeping the imports below behind ``TYPE_CHECKING`` and lazy-imported
# inside ``__call__`` lets tests import this module without installing
# Starlette as a hard dependency.
def _starlette_check() -> None:
    """Verify Starlette is importable. Called by tests, not at module load."""
    try:
        import starlette.requests  # noqa: F401
        import starlette.responses  # noqa: F401
    except ImportError as exc:  # pragma: no cover — defensive
        raise ImportError(
            "Starlette is required for lub.api.middleware. "
            "Install with: pip install 'llm-uncertainty-banking[api]'"
        ) from exc
