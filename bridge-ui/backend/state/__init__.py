# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Decoupled stateful modules extracted from server.py (audit trail, runtime state).

server.py re-exports / proxies the public names so the _server() surface keeps working.
"""
