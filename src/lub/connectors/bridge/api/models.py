# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Pydantic models for the Bridge REST API.

All request/response schemas for the Bridge platform API. Uses Pydantic v2
for validation and serialization. Every response includes a ``confidence``
field so consumers know how much to trust the AI-generated content.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Channel(StrEnum):
    """Supported customer interaction channels."""

    APP = "app"
    WHATSAPP = "whatsapp"
    WEB = "web"
    CALL_CENTER = "call_center"


class Decision(StrEnum):
    """Guard decision for a query."""

    PASSTHROUGH = "passthrough"
    FLAG = "flag"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


# ---- Request models ----


class QueryRequest(BaseModel):
    """Customer query with routing metadata."""

    query: str = Field(..., min_length=1, max_length=4096, description="Customer question")
    channel: Channel = Channel.APP
    customer_id: str = Field(default="", description="Customer identifier for context")
    session_id: str = Field(default="", description="Conversation session")
    language: str = Field(default="pt-BR", description="Query language")


class AgentRegisterRequest(BaseModel):
    """Register a new agent in the Bridge platform."""

    name: str = Field(..., min_length=1, max_length=100)
    agent_type: str = Field(..., description="chatbot | call_center | smart_payments | custom")
    config: dict[str, Any] = Field(default_factory=dict)


# ---- Response models ----


class QueryResponse(BaseModel):
    """AI-generated answer with confidence and decision metadata."""

    answer: str
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence")
    decision: Decision = Decision.PASSTHROUGH
    intent: str = ""
    agent_used: str = ""
    escalated: bool = False
    latency_ms: float = 0.0
    session_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Platform health check response."""

    status: str = "ok"
    version: str = "0.1.0"
    agents_registered: int = 0
    uptime_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentInfo(BaseModel):
    """Information about a registered agent."""

    name: str
    agent_type: str
    status: str = "active"
    queries_handled: int = 0
    avg_confidence: float = 0.0
    escalation_rate: float = 0.0


class MetricsResponse(BaseModel):
    """Operational metrics snapshot."""

    total_queries: int = 0
    resolution_rate: float = 0.0
    escalation_rate: float = 0.0
    avg_confidence: float = 0.0
    avg_latency_ms: float = 0.0
    queries_by_channel: dict[str, int] = Field(default_factory=dict)
    queries_by_intent: dict[str, int] = Field(default_factory=dict)
    period_hours: int = 24


class ComplianceResponse(BaseModel):
    """Compliance dashboard data."""

    bcb_4893_status: str = "compliant"
    bcbs_239_status: str = "compliant"
    sr_11_7_status: str = "compliant"
    audit_trail_complete: bool = True
    violations: list[dict[str, Any]] = Field(default_factory=list)
    last_check: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str = ""
    code: int = 500


__all__ = [
    "AgentInfo",
    "AgentRegisterRequest",
    "Channel",
    "ComplianceResponse",
    "Decision",
    "ErrorResponse",
    "HealthResponse",
    "MetricsResponse",
    "QueryRequest",
    "QueryResponse",
]
