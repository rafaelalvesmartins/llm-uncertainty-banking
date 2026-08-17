# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Decoupled core domain modules extracted from the server.py monolith.

Each module here is pure, self-contained logic (no server state). server.py
re-exports the public names so the `_server()` surface (routers + tests) keeps
working unchanged during the incremental decoupling.
"""
