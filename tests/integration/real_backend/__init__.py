# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Opt-in real-backend smoke tests.

These tests hit live LLM providers and so are skipped by default. To
run them, export the opt-in env var AND the provider credentials:

    LUB_REAL_BACKEND_TESTS=1  pytest -m real_backend

Each test is a bare-minimum smoke check: one tiny generate() call that
returns a non-empty string and a plausible finish_reason. The point is
to catch SDK drift (upstream breaking changes to openai/anthropic/...)
that the hermetic DummyBackend suite cannot see.
"""
