# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Governed change requests — CRUD behind a dated approval trail (product #4 / v6).

The validator's #4: let an operator *add/alter* things (agent, intent, DQ rule,
RAG doc), but only behind a governed, dated approval workflow that becomes
evidence. This module is the first real slice of that — and the first PERSISTED
state in the product (SQLite, survives restart, unlike the in-memory demo).

A change is submitted (status=pending), then a DIFFERENT operator approves or
rejects it (segregation of duties — SR 11-7 independent validation). Every step
is dated and attributed. Identity here is an honest *demo operator* selected in
the UI — NOT production authentication (that is the v6 auth phase). Persistence:
``BRIDGE_CHANGES_DB`` (defaults to a temp file; tests use ``:memory:``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

try:
    from backend.routers.auth import verify_token
except ImportError:
    from routers.auth import verify_token  # type: ignore[no-redef]

try:
    from backend.backends import is_demo_safe
except ImportError:
    from backends import is_demo_safe  # type: ignore[no-redef]


def _server() -> ModuleType:
    """Reuse whichever ``server`` module is already loaded so this router's audit
    writes hit the SAME hash-chain the /query hot-path reads — never a divergent
    second module instance (the documented audit-identity trap). Lazy: not imported
    at module load, so there is no circular import with server.py."""
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


router = APIRouter()

_DB_PATH = os.environ.get(
    "BRIDGE_CHANGES_DB", str(Path(os.environ.get("TMP", "/tmp")) / "bridge_changes.db")
)
_DB: sqlite3.Connection | None = None
_LOCK = threading.Lock()
_KINDS = {"agent", "intent", "dq_rule", "rag_doc", "channel", "provider", "channel_policy"}
# Demo-safe channel allow-list: ``type`` values that are loopback/demo-only and never
# send to a real external endpoint, so the demo-safe floor lets them apply end-to-end.
# Anything NOT in here is treated as send-capable and refused by _is_real_binding().
# SINGLE SOURCE for the server-side gate — keep in sync with the UI CHANNEL_TYPES in
# frontend/components/console/ConnectionGovernance.tsx (the non-real entries must match).
# NOTE: this is the security gate; the server decides, never a client-supplied is_real.
_DEMO_SAFE_CHANNELS = frozenset({"", "app", "web", "call_center", "fake", "loopback", "fakewhatsapp"})
# Fields whose raw value must NEVER touch SQLite, logs, or the audit trail.
_SECRET_FIELDS = frozenset(
    {"access_token", "app_secret", "verify_token", "api_key", "token", "secret", "password"}
)


def _db() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        _DB = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _DB.row_factory = sqlite3.Row
        _DB.execute(
            """CREATE TABLE IF NOT EXISTS change_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload TEXT,
                submitted_by TEXT NOT NULL,
                submitted_at REAL NOT NULL,
                status TEXT NOT NULL,
                reviewer TEXT,
                decided_at REAL,
                decision_note TEXT,
                config_hash TEXT,
                applied_by TEXT,
                applied_at REAL,
                apply_result TEXT,
                prev_snapshot TEXT
            )"""
        )
        # System-of-record: the LIVE config, distinct from the append-only proposal
        # ledger above. apply_change() writes here; reads never expose raw secrets.
        _DB.execute(
            """CREATE TABLE IF NOT EXISTS active_configs (
                domain TEXT NOT NULL,        -- 'provider' | 'channel'
                name TEXT NOT NULL,          -- instance name
                config TEXT NOT NULL,        -- masked JSON (never raw secrets)
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL,
                updated_by TEXT,
                PRIMARY KEY (domain, name)
            )"""
        )
        _migrate(_DB)
        _DB.commit()
    return _DB


def _migrate(db: sqlite3.Connection) -> None:
    """SQLite has no ``ADD COLUMN IF NOT EXISTS`` — add the governance/apply columns to a
    pre-existing DB only when missing (idempotent via ``PRAGMA table_info``)."""
    have = {r[1] for r in db.execute("PRAGMA table_info(change_requests)").fetchall()}
    for col, decl in (
        ("config_hash", "TEXT"),
        ("applied_by", "TEXT"),
        ("applied_at", "REAL"),
        ("apply_result", "TEXT"),
        ("prev_snapshot", "TEXT"),
    ):
        if col not in have:
            db.execute(f"ALTER TABLE change_requests ADD COLUMN {col} {decl}")


class SubmitRequest(BaseModel):
    kind: str = Field(..., max_length=64)
    summary: str = Field(..., min_length=1, max_length=500)
    submitted_by: str = Field(..., max_length=128)
    payload: dict[str, Any] | None = None


class DecisionRequest(BaseModel):
    decision: str = Field(..., max_length=16)  # "approve" | "reject"
    reviewer: str = Field(..., max_length=128)
    note: str = Field("", max_length=500)


class ApplyRequest(BaseModel):
    applier: str = Field("", max_length=128)  # used only when BRIDGE_AUTH=off; otherwise the token subject applies


def _mask(value: Any) -> str:
    s = str(value)
    return "••••" + s[-4:] if len(s) >= 4 else "••••"


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with every secret field masked at ANY depth (nested dicts + lists),
    not just the top level — a flat pass would leak e.g. ``{"config": {"api_key": ...}}``
    into SQLite and the audit chain. Idempotent: ``{"_masked": ...}`` is left untouched."""

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {
                k: (
                    {"_masked": _mask(x) if x not in (None, "") else "••••"}
                    if k in _SECRET_FIELDS and not (isinstance(x, dict) and "_masked" in x)
                    else walk(x)
                )
                for k, x in v.items()
            }
        if isinstance(v, list):
            return [walk(i) for i in v]
        return v

    return walk(payload)


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _config_hash(payload: dict[str, Any]) -> str:
    """Hash the (already-masked) payload so an approval is bound to exact bytes (TOCTOU)."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _is_real_binding(kind: str, payload: dict[str, Any]) -> bool:
    """True if applying this would touch a real LLM or a send-capable external channel —
    the bindings the demo-safe floor must refuse."""
    t = str(payload.get("type", "")).lower()
    if kind == "provider":
        return payload.get("is_real") is True or t not in ("", "fake", "fakebackend")
    if kind == "channel":
        return t not in _DEMO_SAFE_CHANNELS
    return False


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = {k: r[k] for k in r.keys()}  # noqa: SIM118  (sqlite3.Row: iterating it yields values, not keys; .keys() is required)
    d["payload"] = _redact(json.loads(d.get("payload") or "{}"))
    return d


def _chain_append(entry: dict[str, Any], *, what: str) -> None:
    """Record a governance lifecycle event on the SAME tamper-evident hash-chain the
    /query path uses (SR 11-7 / BCB 4893), so submit → decision → apply are ALL
    detectable-tamper, not just the final apply.

    Contract (identical for every caller): called AFTER the SQLite commit and OUTSIDE
    ``_LOCK`` (the audit module has its own lock — don't nest), with a MASKED payload
    only, and best-effort: a change that is already committed must never fail because
    the audit sink hiccuped. Routed through ``_server()`` to hit the one canonical
    audit module (which stamps seq/prev_hash/hash).
    """
    try:
        _server()._audit_append(entry)
    except Exception as e:
        print(f"[governance] audit-chain append failed for {what}: {e}", flush=True)


def submit_change(kind: str, summary: str, submitted_by: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if kind not in _KINDS:
        # Reject an unknown kind outright (422) instead of silently coercing it to
        # "other" — a typo must not become a stored, un-appliable change.
        raise HTTPException(status_code=422, detail=f"unknown kind {kind!r}; allowed: {sorted(_KINDS)}")
    if len(summary.strip()) > 500:
        # Cap free-text so a huge summary can't break the trail layout or bloat the
        # append-only ledger. Mirrors SubmitRequest.summary for direct callers/tests.
        raise HTTPException(status_code=422, detail="summary too long (max 500 characters)")
    k = kind
    # Strip raw secrets BEFORE anything is persisted (defense at rest, not just on read),
    # then bind the approval to these exact bytes via config_hash.
    clean = _redact(payload or {})
    chash = _config_hash(clean)
    now = time.time()
    with _LOCK:
        db = _db()
        # Non-blocking duplicate check: an identical kind+summary that's still live
        # (pending/approved/applied) is almost always an accidental re-submit. We warn
        # but still record it — the ledger is append-only evidence, not a unique index.
        dups = db.execute(
            "SELECT id FROM change_requests WHERE kind=? AND summary=? "
            "AND status IN ('pending','approved','applied') ORDER BY id",
            (k, summary.strip()),
        ).fetchall()
        cur = db.execute(
            "INSERT INTO change_requests (kind,summary,payload,submitted_by,submitted_at,status,config_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (k, summary.strip(), json.dumps(clean), submitted_by, now, "pending", chash),
        )
        db.commit()
        result: dict[str, Any] = {"id": cur.lastrowid, "status": "pending", "config_hash": chash}
        if dups:
            ids = ", ".join(f"#{r['id']}" for r in dups)
            result["duplicate_warning"] = (
                f"A {k} change with the same summary already exists ({ids}) and is still live — "
                "submitted anyway; review for a possible duplicate."
            )
    # Tamper-evident trail: the PROPOSAL is evidence too. Without this, only the apply was
    # hash-chained and the submit/approve rows lived in mutable SQLite — i.e. the "approvals
    # are tamper-evident" claim covered 1 of the 3 lifecycle steps. Same contract as apply
    # (see apply_change): after the commit, outside _LOCK, masked payload, best-effort.
    _chain_append(
        {
            "ts": now,
            "event": "governance.submit",
            "change_id": result["id"],
            "kind": k,
            "summary": summary.strip(),
            "submitted_by": submitted_by,
            "config_hash": chash,
            "payload": clean,
            "decision": "PENDING",
        },
        what=f"submit {result['id']}",
    )
    return result


def decide_change(change_id: int, decision: str, reviewer: str, note: str = "") -> dict[str, Any]:
    status = "approved" if decision == "approve" else "rejected"
    now = time.time()
    with _LOCK:
        db = _db()
        row = db.execute("SELECT * FROM change_requests WHERE id=?", (change_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="change not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="change already decided")
        if reviewer == row["submitted_by"]:
            raise HTTPException(
                status_code=400,
                detail="reviewer must differ from submitter (segregation of duties / SR 11-7)",
            )
        db.execute(
            "UPDATE change_requests SET status=?,reviewer=?,decided_at=?,decision_note=? WHERE id=?",
            (status, reviewer, now, note, change_id),
        )
        db.commit()
    # The APPROVAL is the SoD control itself — hash-chain it so who-approved-what-when
    # cannot be quietly rewritten in the mutable change_requests row.
    _chain_append(
        {
            "ts": now,
            "event": "governance.decision",
            "change_id": change_id,
            "kind": row["kind"],
            "submitted_by": row["submitted_by"],
            "reviewer": reviewer,
            "decision": status.upper(),  # APPROVED | REJECTED
            "decision_note": note,
            "config_hash": row["config_hash"],
        },
        what=f"decision {change_id}",
    )
    return {"id": change_id, "status": status}


def list_changes() -> dict[str, Any]:
    db = _db()
    rows = db.execute("SELECT * FROM change_requests ORDER BY id DESC").fetchall()
    items = [_row(r) for r in rows]
    by_status: dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    return {"n": len(items), "by_status": by_status, "changes": items}


def apply_change(change_id: int, applier: str, *, demo_safe: bool | None = None) -> dict[str, Any]:
    """Execute an APPROVED change into the live system-of-record — the primitive the whole
    governance loop existed to enable (without it an approved change is dead data).

    Guards: status must be ``approved`` (replay), ``applier`` must differ from BOTH the
    submitter and the reviewer (four-eyes — the approver cannot also execute), the payload
    must still hash to the approved bytes (TOCTOU), and the demo-safe floor refuses any
    real/send-capable binding.
    """
    safe = is_demo_safe() if demo_safe is None else demo_safe
    with _LOCK:
        db = _db()
        row = db.execute("SELECT * FROM change_requests WHERE id=?", (change_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="change not found")
        if row["status"] != "approved":
            raise HTTPException(
                status_code=409, detail=f"change is {row['status']!r}, not 'approved' (already applied?)"
            )
        if applier == row["submitted_by"]:
            raise HTTPException(
                status_code=400,
                detail="applier must differ from submitter (segregation of duties on apply / SR 11-7)",
            )
        if row["reviewer"] and applier == row["reviewer"]:
            raise HTTPException(
                status_code=400,
                detail="applier must differ from the reviewer — the approver cannot also execute "
                "(four-eyes separation / SR 11-7)",
            )
        payload = json.loads(row["payload"] or "{}")
        if row["config_hash"] and _config_hash(payload) != row["config_hash"]:
            raise HTTPException(status_code=409, detail="payload changed since approval (config_hash mismatch)")
        # A "remove" change deletes the live object; the demo-safe floor only blocks
        # *binding* a real vendor — removing one is always allowed.
        op = str(payload.get("op") or "upsert").lower()
        if op != "remove" and safe and _is_real_binding(row["kind"], payload):
            raise HTTPException(
                status_code=409,
                detail="BRIDGE_DEMO_SAFE=on refuses to apply a real provider / send-capable channel",
            )
        # The change kind IS the system-of-record domain (provider/channel/agent/intent/
        # dq_rule/rag_doc), so apply works uniformly for every governed kind.
        domain = row["kind"]
        name = str(payload.get("name") or payload.get("title") or payload.get("type") or f"{domain}-{change_id}")
        prev = db.execute(
            "SELECT config FROM active_configs WHERE domain=? AND name=?", (domain, name)
        ).fetchone()
        prev_snapshot = prev["config"] if prev else None
        now = time.time()
        if op == "remove":
            db.execute("DELETE FROM active_configs WHERE domain=? AND name=?", (domain, name))
            apply_result = "removed"
        else:
            # Mutate the live system-of-record (masked config only — never raw secrets).
            db.execute(
                "INSERT INTO active_configs (domain,name,config,enabled,updated_at,updated_by) "
                "VALUES (?,?,?,1,?,?) "
                "ON CONFLICT(domain,name) DO UPDATE SET "
                "config=excluded.config, enabled=excluded.enabled, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (domain, name, json.dumps(_redact(payload)), now, applier),
            )
            apply_result = "applied"
        db.execute(
            "UPDATE change_requests SET status=?, applied_by=?, applied_at=?, apply_result=?, prev_snapshot=? WHERE id=?",
            ("applied", applier, now, apply_result, prev_snapshot, change_id),
        )
        db.commit()
    # Tamper-evident trail (SR 11-7 / BCB 4893): the third and final lifecycle event.
    # Together with governance.submit and governance.decision, the WHOLE governed change
    # (who proposed, who approved, who executed) is on the hash chain — see _chain_append.
    _chain_append(
        {
            "ts": now,
            "event": "governance.apply",
            "change_id": change_id,
            "kind": row["kind"],
            "domain": domain,
            "name": name,
            "submitted_by": row["submitted_by"],
            "approved_by": row["reviewer"],
            "applied_by": applier,
            "config_hash": row["config_hash"],
            "after": _redact(payload),
            "decision": "APPLIED",
        },
        what=f"change {change_id}",
    )
    return {"id": change_id, "status": "applied", "applied_by": applier, "domain": domain, "name": name, "result": apply_result}


def active_channel_policy(channel: str) -> dict[str, Any] | None:
    """Applied firewall policy for a channel — ``{"allowed_intents": [...], ...}`` or
    ``None``. Read-only; the /query pipeline calls this to enforce a per-channel intent
    allow-list (default-deny → ESCALATE for off-list intents). Keyed by the channel
    value (e.g. ``whatsapp``/``app``) so it matches ``QueryRequest.channel``."""
    if not channel:
        return None
    with _LOCK:
        row = _db().execute(
            "SELECT config FROM active_configs WHERE domain='channel_policy' AND name=? AND enabled=1",
            (channel,),
        ).fetchone()
    if not row:
        return None
    try:
        cfg = json.loads(row["config"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    return cfg if isinstance(cfg, dict) else None


def active_intent_policies() -> dict[str, dict[str, Any]]:
    """Applied governed intent decision policies, keyed by intent name. Read-only; the
    ``/query`` pipeline consults this so an approved + applied ``intent`` change actually
    takes effect — a NEW intent becomes classifiable via its sample utterances, and any
    intent gets a governed decision / threshold override. Intent policies carry no
    secrets, so they are returned unmasked."""
    with _LOCK:
        rows = _db().execute(
            "SELECT name, config FROM active_configs WHERE domain='intent' AND enabled=1",
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            cfg = json.loads(row["config"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(cfg, dict):
            out[str(row["name"])] = cfg
    return out


def active_configs(domain: str | None = None) -> dict[str, Any]:
    """The live system-of-record (masked). What ``/query`` reflects on the next request."""
    db = _db()
    if domain:
        rows = db.execute(
            "SELECT * FROM active_configs WHERE domain=? ORDER BY name", (domain,)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM active_configs ORDER BY domain, name").fetchall()
    items = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}  # noqa: SIM118
        d["config"] = _redact(json.loads(d.get("config") or "{}"))
        items.append(d)
    return {"n": len(items), "configs": items}


@router.post("/governance/changes")
def submit_endpoint(
    req: SubmitRequest, principal: dict[str, Any] | None = Depends(verify_token)
) -> dict[str, Any]:
    """Submit a governed change request (status=pending). When authenticated, the
    submitter is the verified token subject (the body field is ignored)."""
    submitted_by = principal["sub"] if principal else req.submitted_by
    return submit_change(req.kind, req.summary, submitted_by, req.payload)


@router.get("/governance/changes")
def list_endpoint() -> dict[str, Any]:
    """List change requests (newest first) with status counts."""
    return list_changes()


@router.post("/governance/changes/{change_id}/decision")
def decision_endpoint(
    change_id: int, req: DecisionRequest, principal: dict[str, Any] | None = Depends(verify_token)
) -> dict[str, Any]:
    """Approve or reject a pending change. When authenticated, the reviewer is the
    verified token subject — so the segregation-of-duties check compares two
    signature-bound identities — and RBAC requires a validator/admin role to decide
    (v6 Phase 2): an analyst can submit but not approve its own line of work."""
    if principal is not None:
        roles = principal.get("roles", [])
        if "validator" not in roles and "admin" not in roles:
            raise HTTPException(
                status_code=403,
                detail="role 'validator' or 'admin' required to decide a change request",
            )
        reviewer = principal["sub"]
    else:
        reviewer = req.reviewer
    result = decide_change(change_id, req.decision, reviewer, req.note)
    # Honesty signal (architecture audit): when BRIDGE_AUTH=off the SoD check
    # compares two UNVERIFIED request fields — it looks like independent-reviewer
    # validation but isn't cryptographically bound. Surface that explicitly so the
    # UI / an auditor is never misled into trusting an unenforced control.
    result["sod_enforced"] = principal is not None
    if principal is None:
        result["sod_warning"] = (
            "BRIDGE_AUTH=off — segregation of duties is NOT cryptographically enforced "
            "(submitter/reviewer are unverified request fields). Set BRIDGE_AUTH=on for "
            "signature-bound SoD (v6 Phase 1)."
        )
    return result


@router.post("/governance/changes/{change_id}/apply")
def apply_endpoint(
    change_id: int, req: ApplyRequest, principal: dict[str, Any] | None = Depends(verify_token)
) -> dict[str, Any]:
    """Apply an approved change to the live config. When authenticated, the applier is the
    verified token subject and RBAC requires validator/admin — and the SoD-on-apply check
    means the submitter cannot rubber-stamp and apply its own work."""
    if principal is not None:
        roles = principal.get("roles", [])
        if "validator" not in roles and "admin" not in roles:
            raise HTTPException(
                status_code=403, detail="role 'validator' or 'admin' required to apply a change request"
            )
        applier = principal["sub"]
    else:
        applier = req.applier
    if not applier:
        raise HTTPException(status_code=400, detail="applier required")
    result = apply_change(change_id, applier)
    result["sod_enforced"] = principal is not None
    if principal is None:
        result["sod_warning"] = (
            "BRIDGE_AUTH=off — apply segregation of duties compares unverified request "
            "fields. Set BRIDGE_AUTH=on for signature-bound apply."
        )
    return result


@router.get("/governance/active-configs")
def active_configs_endpoint(domain: str | None = None) -> dict[str, Any]:
    """The live system-of-record (provider/channel), masked. Never returns raw secrets."""
    return active_configs(domain)


__all__ = ["router"]
