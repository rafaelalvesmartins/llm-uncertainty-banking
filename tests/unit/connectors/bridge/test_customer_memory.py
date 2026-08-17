# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.customer_memory``."""

from __future__ import annotations

import pytest

from lub.connectors.bridge.customer_memory import (
    STANDARD_BLOCKS,
    CustomerMemory,
    InMemoryMemoryStore,
    MemoryBlock,
    MemoryStore,
)

# ---------------------------------------------------------------------------
# MemoryBlock validation
# ---------------------------------------------------------------------------


class TestMemoryBlockValidation:
    def test_valid_block_constructs(self) -> None:
        block = MemoryBlock(name="persona", content="ok", updated_at=1.0)
        assert block.name == "persona"
        assert block.content == "ok"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            MemoryBlock(name="", content="x", updated_at=1.0)

    def test_oversize_content_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            MemoryBlock(name="x", content="x" * 3000, updated_at=1.0)


# ---------------------------------------------------------------------------
# Store basics
# ---------------------------------------------------------------------------


class TestInMemoryStore:
    def test_implements_protocol(self) -> None:
        assert isinstance(InMemoryMemoryStore(), MemoryStore)

    def test_get_blocks_empty_when_unknown_customer(self) -> None:
        store = InMemoryMemoryStore()
        assert store.get_blocks("c-unknown") == {}

    def test_put_and_get_round_trip(self) -> None:
        store = InMemoryMemoryStore()
        block = MemoryBlock(name="persona", content="x", updated_at=1.0)
        store.put_block("c1", block)
        assert store.get_blocks("c1")["persona"] is block

    def test_delete_returns_true_when_present(self) -> None:
        store = InMemoryMemoryStore()
        store.put_block("c1", MemoryBlock(name="x", content="y", updated_at=1.0))
        assert store.delete_block("c1", "x") is True

    def test_delete_returns_false_when_absent(self) -> None:
        store = InMemoryMemoryStore()
        assert store.delete_block("c1", "nope") is False

    def test_list_customers_returns_sorted(self) -> None:
        store = InMemoryMemoryStore()
        store.put_block("zebra", MemoryBlock(name="x", content="y", updated_at=1.0))
        store.put_block("apple", MemoryBlock(name="x", content="y", updated_at=1.0))
        assert store.list_customers() == ["apple", "zebra"]


# ---------------------------------------------------------------------------
# CustomerMemory facade
# ---------------------------------------------------------------------------


class TestCustomerMemoryFacade:
    def setup_method(self) -> None:
        self.memory = CustomerMemory(store=InMemoryMemoryStore())

    def test_invalid_store_raises(self) -> None:
        class NotAStore:
            pass

        with pytest.raises(TypeError, match="MemoryStore"):
            CustomerMemory(store=NotAStore())  # type: ignore[arg-type]

    def test_update_creates_block(self) -> None:
        block = self.memory.update_block("c1", "persona", "PF conservador")
        assert block.content == "PF conservador"
        assert block.update_count == 1

    def test_update_increments_count_on_replace(self) -> None:
        self.memory.update_block("c1", "persona", "v1")
        block = self.memory.update_block("c1", "persona", "v2")
        assert block.update_count == 2
        assert block.content == "v2"

    def test_update_empty_customer_id_raises(self) -> None:
        with pytest.raises(ValueError, match="customer_id"):
            self.memory.update_block("", "persona", "x")

    def test_get_block_returns_none_when_missing(self) -> None:
        assert self.memory.get_block("c1", "anything") is None

    def test_snapshot_returns_all_blocks(self) -> None:
        self.memory.update_block("c1", "persona", "p1")
        self.memory.update_block("c1", "preferences", "TED")
        snap = self.memory.snapshot("c1")
        assert set(snap.keys()) == {"persona", "preferences"}

    def test_snapshot_isolated_per_customer(self) -> None:
        self.memory.update_block("c1", "persona", "p1")
        self.memory.update_block("c2", "persona", "p2")
        assert self.memory.snapshot("c1")["persona"].content == "p1"
        assert self.memory.snapshot("c2")["persona"].content == "p2"

    def test_delete_block_returns_bool(self) -> None:
        self.memory.update_block("c1", "persona", "p1")
        assert self.memory.delete_block("c1", "persona") is True
        assert self.memory.delete_block("c1", "persona") is False


# ---------------------------------------------------------------------------
# Append behavior
# ---------------------------------------------------------------------------


class TestAppendBlock:
    def setup_method(self) -> None:
        self.memory = CustomerMemory(store=InMemoryMemoryStore())

    def test_append_to_empty_creates_block(self) -> None:
        block = self.memory.append_to_block("c1", "concerns", "first issue")
        assert block.content == "first issue"

    def test_append_concatenates_with_separator(self) -> None:
        self.memory.append_to_block("c1", "concerns", "first")
        block = self.memory.append_to_block("c1", "concerns", "second")
        assert "first" in block.content
        assert "second" in block.content

    def test_append_truncates_when_oversize(self) -> None:
        long_text = "x" * 1900
        self.memory.append_to_block("c1", "concerns", long_text)
        block = self.memory.append_to_block("c1", "concerns", "y" * 200)
        # After truncation, length is at most 2000.
        assert len(block.content) <= 2000
        # And the most recent text is preserved at the end.
        assert block.content.endswith("y" * 200)


# ---------------------------------------------------------------------------
# Render prompt context
# ---------------------------------------------------------------------------


class TestRenderPromptContext:
    def setup_method(self) -> None:
        self.memory = CustomerMemory(store=InMemoryMemoryStore())

    def test_empty_customer_returns_empty_string(self) -> None:
        assert self.memory.render_prompt_context("c-unknown") == ""

    def test_renders_standard_blocks_first(self) -> None:
        self.memory.update_block("c1", "custom_field", "extra")
        self.memory.update_block("c1", "persona", "PF")
        self.memory.update_block("c1", "preferences", "TED")
        rendered = self.memory.render_prompt_context("c1")
        # persona must appear before custom_field
        assert rendered.index("persona") < rendered.index("custom_field")
        assert rendered.index("preferences") < rendered.index("custom_field")

    def test_includes_block_content(self) -> None:
        self.memory.update_block("c1", "persona", "PF conservador")
        rendered = self.memory.render_prompt_context("c1")
        assert "PF conservador" in rendered
        assert "# Customer memory" in rendered


# ---------------------------------------------------------------------------
# Standard blocks contract
# ---------------------------------------------------------------------------


class TestStandardBlocks:
    def test_includes_expected_names(self) -> None:
        assert "persona" in STANDARD_BLOCKS
        assert "preferences" in STANDARD_BLOCKS
        assert "recent_concerns" in STANDARD_BLOCKS
