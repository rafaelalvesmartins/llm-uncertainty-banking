"""Opt-in scale layer (Track D of docs/ENGINEERING_HARDENING_PLAN.md).

Every module here is ADDITIVE and FLAG-GATED — nothing is wired into the running
demo. With no REDIS_URL / DATABASE_URL set, the app behaves exactly as today
(in-process state, SQLite audit). These adapters mirror the existing in-process
interfaces so they can be swapped in later behind a flag (see docs/SCALE_WIRING.md).

NOT production-validated in this form: each adapter ships with tests that must be
run against a real Redis/Postgres, and the Postgres audit store must be validated
against the existing SQLite hash-chain before it is ever trusted.
"""
