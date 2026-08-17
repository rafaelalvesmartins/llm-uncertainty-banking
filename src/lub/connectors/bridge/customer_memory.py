# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Long-term per-customer memory ("self-editing memory blocks").

Inspired by ``letta-ai/letta`` (formerly MemGPT, Apache-2.0): an agent
should carry stable knowledge about *who it is talking to* across
sessions, not just within one conversation. The :class:`SemanticCache`
already added (see :mod:`lub.connectors.bridge.memory`) helps the
*platform* (cache common queries); this module helps the *customer*
(remember their preferences, recurring concerns, persona).

Differences from SemanticCache
------------------------------

* **Granularity**: cache is per-query (any customer); memory is per-customer.
* **Persistence**: cache is bounded in-process; memory is intended to
  outlive the process — backed by an injectable :class:`MemoryStore`
  (in-memory default, swap for SQLite/Postgres in production).
* **Update pattern**: cache writes after every answer; memory only
  updates when the agent explicitly calls :meth:`update_block`,
  preventing accidental noise.

Standard memory blocks
----------------------

* ``persona`` — stable customer profile ("PF, perfil conservador").
* ``preferences`` — operational habits ("prefere TED, fatura dia 5").
* ``recent_concerns`` — short-term issues to acknowledge ("reclamou
  IOF semana passada").
* ``custom`` — free-form blocks for product-specific extensions.

Banking notes
-------------

* All blocks have a max length so a runaway agent cannot bloat
  per-customer storage.
* Block updates are timestamped so the audit trail can answer "what
  did the system know about this customer at the moment of decision X".
* PII handling is the *caller's* responsibility: this module stores
  whatever you pass. Don't put unhashed CPF/CNPJ in blocks; put a
  derived attribute ("tax_status: ME") instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

import structlog

__all__ = [
    "CustomerMemory",
    "InMemoryMemoryStore",
    "MemoryBlock",
    "MemoryStore",
    "STANDARD_BLOCKS",
]

_LOG = structlog.get_logger("lub.bridge.customer_memory")

# Reserved block names. Agents can also create custom blocks but these
# are documented and surfaced first in audit views.
STANDARD_BLOCKS: Final = ("persona", "preferences", "recent_concerns")

# Hard cap on block content length to bound storage per customer.
_MAX_BLOCK_CHARS: Final = 2000


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MemoryBlock:
    """A single named block of persistent customer state."""

    name: str
    content: str
    updated_at: float
    update_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("block name must be non-empty")
        if len(self.content) > _MAX_BLOCK_CHARS:
            raise ValueError(
                f"block '{self.name}' content exceeds {_MAX_BLOCK_CHARS} chars "
                f"(got {len(self.content)})"
            )


# ---------------------------------------------------------------------------
# Storage protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryStore(Protocol):
    """Pluggable persistence layer. Default impl is in-memory; production
    deployments should provide a SQLite or Postgres-backed store."""

    def get_blocks(self, customer_id: str) -> dict[str, MemoryBlock]:
        """Return every memory block for ``customer_id`` keyed by block name.

        Bridge stage 3 (CustomerMemory load) calls this just before the RAG
        and agent stages so the LLM prompt is hydrated with persona /
        preferences / recent_concerns. Empty dict when the customer is
        unknown — callers must not assume membership.
        """
        ...

    def put_block(self, customer_id: str, block: MemoryBlock) -> None:
        """Persist or overwrite a single block under ``customer_id``.

        Bridge writes here whenever an agent explicitly updates customer
        state (e.g. smart_payments registering a new payment preference)
        so the next conversation can resume with that fact remembered.
        """
        ...

    def delete_block(self, customer_id: str, name: str) -> bool:
        """Remove the named block; return ``True`` iff something was deleted.

        Bridge invokes this for LGPD/right-to-be-forgotten requests and
        for stale-data cleanup (e.g. clearing ``recent_concerns`` after a
        resolved complaint). The boolean lets the audit trail distinguish
        "deleted" from "already absent".
        """
        ...

    def list_customers(self) -> list[str]:
        """List every customer that has at least one stored block.

        Bridge admin/analytics surfaces (governance dashboards, BCB 4893
        audit sweeps) iterate this to enumerate known customers without
        scanning live conversations.
        """
        ...


@dataclass
class InMemoryMemoryStore:
    """Reference implementation. Stable across one process lifetime."""

    _data: dict[str, dict[str, MemoryBlock]] = field(default_factory=dict)

    def get_blocks(self, customer_id: str) -> dict[str, MemoryBlock]:
        """Return a defensive shallow copy of the customer's blocks.

        Bridge stage 3 hydrates the prompt from this snapshot; the copy
        prevents callers from mutating the store's internal state.
        """
        return dict(self._data.get(customer_id, {}))

    def put_block(self, customer_id: str, block: MemoryBlock) -> None:
        """Store ``block`` under ``customer_id``, replacing any prior block of the same name.

        Bridge's :class:`CustomerMemory` facade routes every write through
        here, so this is the single insertion point for per-customer state.
        """
        self._data.setdefault(customer_id, {})[block.name] = block

    def delete_block(self, customer_id: str, name: str) -> bool:
        """Delete the named block; return ``True`` iff it existed.

        Bridge calls this for LGPD erasure and stale-block cleanup. The
        return value drives the audit log emitted upstream so we record
        a deletion event only when something was actually removed.
        """
        if customer_id in self._data and name in self._data[customer_id]:
            del self._data[customer_id][name]
            return True
        return False

    def list_customers(self) -> list[str]:
        """Return the sorted roster of customers with any stored blocks.

        Bridge governance / analytics modules call this to enumerate known
        customers; sorting keeps audit output deterministic across runs.
        """
        return sorted(self._data.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class CustomerMemory:
    """High-level facade for a single customer's memory.

    Usage::

        memory = CustomerMemory(store=InMemoryMemoryStore())
        memory.update_block("c-123", "preferences", "prefere TED, fatura dia 5")
        memory.update_block("c-123", "persona", "PF conservador")
        # later, in agent...
        snapshot = memory.snapshot("c-123")
        prompt = build_prompt_with_memory(snapshot, query)
    """

    store: MemoryStore

    def __post_init__(self) -> None:
        # Validate the store conforms to the protocol — fail fast.
        if not isinstance(self.store, MemoryStore):
            raise TypeError(
                f"store must implement MemoryStore protocol (got {type(self.store).__name__})"
            )

    # ---- writes ----

    def update_block(
        self,
        customer_id: str,
        name: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryBlock:
        """Create or replace a block. Returns the new block."""
        if not customer_id:
            raise ValueError("customer_id must be non-empty")
        existing = self.store.get_blocks(customer_id).get(name)
        block = MemoryBlock(
            name=name,
            content=content,
            updated_at=time.time(),
            update_count=(existing.update_count + 1) if existing else 1,
            metadata=metadata or (existing.metadata if existing else {}),
        )
        self.store.put_block(customer_id, block)
        _LOG.info(
            "bridge.customer_memory.updated",
            customer_id=customer_id,
            block=name,
            update_count=block.update_count,
        )
        return block

    def append_to_block(
        self,
        customer_id: str,
        name: str,
        addition: str,
        *,
        separator: str = "\n",
    ) -> MemoryBlock:
        """Append text to an existing block (or create it if absent).

        Useful for accumulating ``recent_concerns`` over time.
        """
        existing = self.store.get_blocks(customer_id).get(name)
        if existing is None:
            return self.update_block(customer_id, name, addition)
        new_content = existing.content + separator + addition
        # Truncate from the front if we exceed the cap (keep most recent).
        if len(new_content) > _MAX_BLOCK_CHARS:
            new_content = new_content[-_MAX_BLOCK_CHARS:]
        return self.update_block(customer_id, name, new_content)

    def delete_block(self, customer_id: str, name: str) -> bool:
        """Delegate deletion to the store and emit a structured audit log entry.

        Bridge wires this to LGPD erasure flows and to agents that decide
        a block (typically ``recent_concerns``) is no longer relevant.
        The structlog event feeds Bridge's stage-9 BCB 4893 audit trail.

        Returns ``True`` iff the block existed and was removed.
        """
        ok = self.store.delete_block(customer_id, name)
        if ok:
            _LOG.info(
                "bridge.customer_memory.deleted",
                customer_id=customer_id,
                block=name,
            )
        return ok

    # ---- reads ----

    def get_block(self, customer_id: str, name: str) -> MemoryBlock | None:
        """Fetch a single named block, or ``None`` if absent.

        Bridge stage 3 uses this when only one block is needed (e.g. just
        ``persona`` for a greeting) to avoid materializing the full
        snapshot. Returns the live :class:`MemoryBlock` — do not mutate
        its fields in-place; call :meth:`update_block` instead.
        """
        return self.store.get_blocks(customer_id).get(name)

    def snapshot(self, customer_id: str) -> dict[str, MemoryBlock]:
        """Return all blocks for a customer (defensive copy)."""
        return self.store.get_blocks(customer_id)

    def render_prompt_context(self, customer_id: str) -> str:
        """Format all blocks as a prompt-ready context string.

        Output is grouped by block name with the standard blocks first
        (deterministic order helps with prompt cache hit rates upstream).
        """
        blocks = self.snapshot(customer_id)
        if not blocks:
            return ""

        # Sort: standard blocks in order, then extras alphabetically.
        ordered_names = [n for n in STANDARD_BLOCKS if n in blocks]
        ordered_names += sorted(n for n in blocks if n not in STANDARD_BLOCKS)

        lines: list[str] = ["# Customer memory"]
        for name in ordered_names:
            block = blocks[name]
            lines.append(f"## {name}")
            lines.append(block.content)
            lines.append("")
        return "\n".join(lines).rstrip()

    def list_customers(self) -> list[str]:
        """Expose the underlying store's customer roster through the facade.

        Bridge admin tooling and governance reports prefer calling this
        on :class:`CustomerMemory` (rather than the raw store) so any
        future cross-cutting concerns — auth, redaction, metrics —
        can be layered here without changing call sites.
        """
        return self.store.list_customers()
