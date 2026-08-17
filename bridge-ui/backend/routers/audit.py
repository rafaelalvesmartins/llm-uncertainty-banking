# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Audit trail endpoints.

Eight endpoints cover the BCB 4893 / SR 11-7 audit-trail surface:

* ``GET    /audit``                — paginated read with filters
* ``DELETE /audit``                — rotate the in-memory window (audited)
* ``GET    /audit/verify``         — re-hash the chain and report intact / broken
* ``GET    /audit/export``         — NDJSON or CSV download (memory or disk source)
* ``GET    /audit/explain/{seq}``  — LGPD Art. 20 explanation by hash-chain seq
* ``GET    /audit/replay/{seq}``   — re-run classifier + guard on a logged query
* ``POST   /audit/tamper-test``    — demonstrate tamper detection
* ``GET    /explain/{audit_index}``— legacy explain by reverse-index (kept)

All endpoints read ``_AUDIT`` (the bounded deque) and the chain head fields
(``_AUDIT_SEQ`` / ``_AUDIT_LAST_HASH``) from ``server.py``. ``DELETE
/audit`` mutates the deque in place and appends a rotation marker via
``server._audit_append``. The tamper-test invokes :func:`audit_verify`
directly (same module, no proxy).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

try:
    from backend.routers.auth import verify_token
except ImportError:  # pragma: no cover
    from routers.auth import verify_token  # type: ignore[no-redef]

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    # Reuse whichever ``server`` module is already loaded so this router's
    # writes and the app's hot-path reads hit the SAME module globals. uvicorn
    # runs ``server:app`` and the tests ``import server`` — both register
    # ``"server"`` in sys.modules. Forcing ``from backend import server`` here
    # would create a divergent second module (runtime state would split).
    import sys
    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


_WITHHELD_MARKER = "[withheld — the guard did not release this answer to the customer]"


def _was_withheld(entry: dict[str, Any]) -> bool:
    """Did the guard hold this answer back from the customer? THE single rule.

    Prefers the fact the pipeline recorded (``answer_withheld``). Falls back to deriving it
    the same way the pipeline does when the key is absent — entries persisted before the flag
    existed rehydrate from SQLite without it, and defaulting those to "released" would hand
    back exactly the answers the guard withheld (fail-open). Never default to released.
    """
    recorded = entry.get("answer_withheld")
    if recorded is not None:
        return bool(recorded)
    return bool(
        _server()._answer_withheld_from_customer(
            str(entry.get("decision", "")), from_cache=bool(entry.get("from_cache", False))
        )
    )


_BLOCKED_MARKER = "[withheld — an output data-quality rule blocked this model output]"


def _redact_withheld_answer(entry: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``entry`` with content the CUSTOMER NEVER RECEIVED replaced by a marker.

    Two kinds of such content:
    * ``answer`` when the guard withheld it (``_was_withheld``);
    * ``blocked_answer`` — the model output an output-DQ rule suppressed (kept on the entry so
      a reviewer can review the block; the customer only ever saw the marker).

    Applied to the BROWSE surface (``GET /audit``) and to an unauthenticated ``/audit/export``,
    so this content isn't one anonymous request away from the explanation that says it was
    withheld. It is retained in the trail itself and in an AUTHENTICATED export (validator /
    admin) — the model-risk evidence artifact, where a reviewer is *supposed* to see what the
    model produced.

    Returns a COPY. It must never mutate the deque entry: the chain hash covers the whole key
    set, so an in-place edit would break ``/audit/verify`` for the life of the process.
    """
    out = entry
    if entry.get("answer") and _was_withheld(entry):
        out = {**out, "answer": _WITHHELD_MARKER, "answer_withheld": True}
    if entry.get("blocked_answer"):
        out = {**out, "blocked_answer": _BLOCKED_MARKER}
    return out


@router.get("/audit")
def audit(
    limit: int = 20,
    offset: int = 0,
    intent: str | None = Query(default=None, description="Filter by intent label (exact match)"),
    decision: str | None = Query(default=None, description="Filter by guard decision (exact match)"),
    channel: str | None = Query(default=None, description="Filter by channel (exact match)"),
    since: float | None = Query(default=None, description="Unix epoch lower bound (inclusive)"),
    until: float | None = Query(default=None, description="Unix epoch upper bound (inclusive)"),
    q: str | None = Query(default=None, description="Substring match against the masked query field"),
) -> dict[str, Any]:
    """Return BCB 4893 audit-trail entries (newest first), with filters.

    Bridge hub connection: read view over the audit log Stage 9 appends to
    on every query; supports the dashboard's compliance / traceability tab.
    """
    s = _server()

    def matches(e: dict[str, Any]) -> bool:
        if intent is not None and e.get("intent") != intent:
            return False
        if decision is not None and e.get("decision") != decision:
            return False
        if channel is not None and e.get("channel") != channel:
            return False
        if since is not None and (e.get("ts") or 0) < since:
            return False
        if until is not None and (e.get("ts") or 0) > until:
            return False
        return not (q is not None and q.lower() not in (e.get("query") or "").lower())

    all_newest_first = [e for e in reversed(list(s._AUDIT)) if matches(e)]
    page = [_redact_withheld_answer(e) for e in all_newest_first[offset : offset + limit]]
    filtered_total = len(all_newest_first)
    return {
        "entries": page,
        "returned": len(page),
        "total": filtered_total,
        "unfiltered_total": len(s._AUDIT),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < filtered_total,
        "chain_head_seq": s._AUDIT_SEQ,
        "chain_head_hash": s._AUDIT_LAST_HASH,
        "filters_applied": {
            k: v
            for k, v in {
                "intent": intent,
                "decision": decision,
                "channel": channel,
                "since": since,
                "until": until,
                "q": q,
            }.items()
            if v is not None
        },
    }


@router.get("/audit/verify")
def audit_verify(
    source: Literal["memory", "disk"] = Query(
        "memory",
        description=(
            "memory = re-hash the current in-memory deque window; "
            "disk = re-validate the FULL persisted SQLite chain. Use disk to catch an "
            "out-of-band / at-rest tamper (e.g. a manual UPDATE of audit_entries) that "
            "happened between restarts — the memory window alone cannot see it."
        ),
    ),
) -> dict[str, Any]:
    """Re-hash the audit chain and verify it is intact.

    Bridge hub connection: SR 11-7 / BCB 4893 reviewers can call this to
    confirm no entry was silently mutated in-place. Returns ``valid: true``
    when every entry's recomputed sha256 matches its stored ``hash`` AND
    each entry's ``prev_hash`` matches the previous entry's ``hash``.

    ``source=memory`` checks the live deque window (fast, but blind to disk-only
    tampering). ``source=disk`` re-runs the same chain validator used at boot over
    every persisted row, so an at-rest edit is detected without a restart — closing
    the gap where the tamper-evidence guarantee previously held only until process exit.
    """
    s = _server()
    if source == "disk":
        db = s._audit_db()
        rows = db.execute(
            "SELECT seq, ts, prev_hash, hash, payload_json FROM audit_entries ORDER BY seq ASC"
        ).fetchall()
        break_seq = s._audit_chain_break(rows)
        return {
            "valid": break_seq is None,
            "source": "disk",
            "checked": len(rows),
            "head_seq": rows[-1][0] if rows else 0,
            "head_hash": rows[-1][3] if rows else "0" * 64,
            "first_failure": (
                None
                if break_seq is None
                else {
                    "seq": break_seq,
                    "reason": (
                        "persisted chain broken at this seq — recomputed sha256 != stored hash, "
                        "or prev_hash does not link to the previous entry (at-rest tamper or corruption)"
                    ),
                }
            ),
        }
    snapshot = list(s._AUDIT)
    if not snapshot:
        return {
            "valid": True,
            "source": "memory",
            "checked": 0,
            "head_seq": s._AUDIT_SEQ,
            "head_hash": s._AUDIT_LAST_HASH,
            "note": "empty audit window — chain head is at genesis or post-rotation",
        }
    first_failure: dict[str, Any] | None = None
    prev_hash_expected: str | None = None
    rotation_marker = False
    if snapshot[0].get("seq") == 1:
        prev_hash_expected = "0" * 64
    else:
        rotation_marker = True
    for entry in snapshot:
        material = json.dumps(
            {
                "seq": entry.get("seq"),
                "prev_hash": entry.get("prev_hash"),
                **{k: v for k, v in entry.items() if k not in ("seq", "prev_hash", "hash")},
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        recomputed = hashlib.sha256(material).hexdigest()
        if recomputed != entry.get("hash"):
            first_failure = {
                "seq": entry.get("seq"),
                "reason": "hash mismatch — entry mutated in place",
                "stored": entry.get("hash"),
                "recomputed": recomputed,
            }
            break
        if prev_hash_expected is not None and entry.get("prev_hash") != prev_hash_expected:
            first_failure = {
                "seq": entry.get("seq"),
                "reason": "broken link — prev_hash does not match previous entry's hash",
                "expected_prev": prev_hash_expected,
                "stored_prev": entry.get("prev_hash"),
            }
            break
        prev_hash_expected = entry.get("hash")
    valid = first_failure is None
    final_entry = snapshot[-1]
    return {
        "valid": valid,
        "source": "memory",
        "checked": len(snapshot),
        "head_seq": s._AUDIT_SEQ,
        "head_hash": s._AUDIT_LAST_HASH,
        "window_first_seq": snapshot[0].get("seq"),
        "window_last_seq": final_entry.get("seq"),
        "window_starts_post_rotation": rotation_marker,
        "first_failure": first_failure,
    }


@router.get("/audit/export", response_model=None)
def audit_export(
    format: Literal["json", "csv"] = Query("json"),
    source: Literal["memory", "disk"] = Query(
        "memory",
        description="memory = current deque window; disk = full SQLite history (may be larger)",
    ),
    principal: dict[str, Any] | None = Depends(verify_token),
) -> StreamingResponse | PlainTextResponse:
    """Download the audit trail as JSON or CSV — the tamper-evident RETENTION ARTIFACT.

    Bridge hub connection: BCB 4893 5-year retention requires the audit log to leave the
    running process, and the whole point of the export is that a model-risk reviewer can
    re-verify the hash chain offline.

    Access, not redaction. The trail deliberately retains the substantive answer even when the
    guard withheld it from the customer — that IS the evidence the reviewer needs. Two things
    follow, and an earlier attempt got both wrong by *redacting* the export:
      * redacting `answer` while keeping seq/prev_hash/hash makes the artifact FAIL its own
        chain verifier (the hash covers the redacted-out bytes) — it would read as tampered;
      * redacting the reviewer's copy defeats the entire purpose of the retention artifact.
    So the export carries the true, chain-verifiable content and is instead ACCESS-CONTROLLED:
    in production (BRIDGE_AUTH on) it requires a validator/admin role; in the demo (auth off,
    synthetic data) it is open like the rest of the console, and the header says so. The
    browse surface (GET /audit) and the explain endpoints still redact — they are viewing
    surfaces, not the verifiable evidence copy.
    """
    s = _server()
    # verify_token returns None ONLY when BRIDGE_AUTH is off (when on, a missing/invalid token
    # raises 401 before we get here). So principal is None ⟺ demo mode ⟹ open. When auth is
    # on we have a verified principal and require a reviewer role.
    if principal is not None:
        roles = principal.get("roles", [])
        if "validator" not in roles and "admin" not in roles:
            raise HTTPException(
                status_code=403,
                detail="role 'validator' or 'admin' required to export the audit retention artifact",
            )
    if source == "memory":
        entries: list[dict[str, Any]] = list(s._AUDIT)
    else:
        db = s._audit_db()
        rows = db.execute(
            """SELECT seq, ts, prev_hash, hash, payload_json
            FROM audit_entries ORDER BY seq ASC"""
        ).fetchall()
        entries = []
        for seq, ts, prev_hash, h, payload_json in rows:
            try:
                payload = json.loads(payload_json)
            except Exception:
                payload = {}
            payload.update({"seq": seq, "ts": ts, "prev_hash": prev_hash, "hash": h})
            entries.append(payload)

    ts_label = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    # Declare what the artifact is. A header, not a top-level field: the JSON export is a bare
    # ARRAY and consumers parse it as such — wrapping it in an object would silently break them.
    _withheld_header = {
        "X-Bridge-Withheld-Answers": "included",
        "X-Bridge-Export-Access": "open-demo" if principal is None else "restricted",
    }
    if format == "json":

        def gen() -> Any:
            yield "[\n"
            for i, e in enumerate(entries):
                yield json.dumps(e, default=str)
                if i < len(entries) - 1:
                    yield ",\n"
                else:
                    yield "\n"
            yield "]\n"

        return StreamingResponse(
            gen(),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="bridge-audit-{source}-{ts_label}.json"',
                **_withheld_header,
            },
        )
    buf = io.StringIO()
    fieldnames = [
        "seq", "ts", "prev_hash", "hash",
        "query", "intent", "confidence", "decision",
        "channel", "from_cache", "tier", "cost_cents",
        "query_was_masked", "pii_count",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        writer.writerow({k: e.get(k, "") for k in fieldnames})
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="bridge-audit-{source}-{ts_label}.csv"',
            **_withheld_header,
        },
    )


_OPERATIONAL_STEP = {
    "governance.submit": "A change was PROPOSED and is awaiting an independent reviewer.",
    "governance.decision": "An independent reviewer DECIDED on the proposed change.",
    "governance.apply": "A third operator EXECUTED the approved change into the live config.",
    "settings.change": "An operator changed a runtime setting (recorded, dated and attributed).",
    "audit.rotation": "An operator rotated the audit window; the rotation itself is recorded "
                      "on the chain so the audit-of-the-audit is unbroken.",
    "visibility.probe": "A synthetic monitoring probe run by the visibility engine — not a "
                        "customer query, and not a decision about any data subject.",
}

# Audit intents that identify an OPERATIONAL entry (operator act / synthetic probe) rather
# than a customer decision. Used to recognise rows that PREDATE the "event" key: the deque is
# rehydrated from SQLite at boot, and rows written before the key existed carry only their
# operational intent — keying purely on "event" would (mis)explain them as LGPD Art. 20
# customer decisions and count them as customer traffic. Same rehydration blind spot that
# once made a confidentiality flag fail open.
_OPERATIONAL_INTENTS = {"audit_rotation", "visibility_collection"}


def _is_operational_entry(entry: dict[str, Any]) -> bool:
    """True for a non-customer audit entry (governed change, settings/drift event, rotation
    marker, visibility probe), robust to SQLite-rehydrated rows that lack the newer ``event``
    key. A real customer query sets none of these signals."""
    if entry.get("event"):
        return True
    if entry.get("intent") in _OPERATIONAL_INTENTS:
        return True
    return entry.get("customer_id") == "visibility-engine"


def _operational_event_label(entry: dict[str, Any]) -> str:
    """The event string for an operational entry — derived for flagless rehydrated rows."""
    ev = str(entry.get("event") or "")
    if ev:
        return ev
    if entry.get("intent") == "audit_rotation":
        return "audit.rotation"
    if entry.get("intent") == "visibility_collection" or entry.get("customer_id") == "visibility-engine":
        return "visibility.probe"
    return "operational"


def _explain_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """THE explanation of one audit entry — used by BOTH explain endpoints.

    There used to be two hand-written copies of this logic (``/audit/explain/{seq}`` and the
    legacy ``/explain/{audit_index}``); fixing one left the other leaking the withheld answer,
    mislabelling operational events as LGPD decisions, and stating the wrong reason. One
    implementation, so a fix cannot land on only half the surface.
    """
    s = _server()
    event = _operational_event_label(entry)
    decision = entry.get("decision", "unknown")
    chain = {
        "seq": entry.get("seq"),
        "prev_hash": entry.get("prev_hash"),
        "hash": entry.get("hash"),
    }

    # An OPERATIONAL event (a governed config change, a settings knob, a drift alert, the
    # rotation marker, a visibility probe) is a HUMAN act of model-risk management or a
    # synthetic probe — not an automated decision about a data subject. Explaining it under
    # LGPD Art. 20 would be legally false, and the customer-decision template would print
    # "intent: Unknown / rationale not recorded" over an entry whose actor is right here.
    # _is_operational_entry also recognises rehydrated rows that predate the "event" key.
    if _is_operational_entry(entry):
        # A GOVERNED change (propose/approve/apply) carries a change_id and went through
        # four-eyes. A settings knob or a drift alert did NOT — calling it a "Governed
        # change #" in the modal would claim a control that never ran. Distinguish them.
        is_governed_change = event.startswith("governance.")
        return {
            "seq": entry.get("seq"),
            "ts": entry.get("ts"),
            "kind": "governance",  # the console's operational-explanation shape
            "operational_kind": "governed_change" if is_governed_change else "operational_event",
            "event": event,
            "change_id": entry.get("change_id"),
            "change_kind": entry.get("kind"),
            "summary": entry.get("summary") or entry.get("detail"),
            "decision": decision,
            "decision_rationale": _OPERATIONAL_STEP.get(
                event, f"Operational event recorded on the audit chain ({event})."
            ),
            "decision_note": entry.get("decision_note"),
            "submitted_by": entry.get("submitted_by") or entry.get("operator"),
            "reviewer": entry.get("reviewer") or entry.get("approved_by"),
            "applied_by": entry.get("applied_by"),
            "config_hash": entry.get("config_hash"),
            "chain": chain,
            "legal_basis": (
                "Model-risk governance evidence: SR 11-7 / BCB 4.893 — dated, attributed and "
                "tamper-evident. This is a human operational decision, NOT an automated "
                "decision about a customer, so LGPD Art. 20 does not apply to it."
            ),
        }

    intent = entry.get("intent", "unknown")
    # Prefer the REAL reason the pipeline recorded (e.g. the DQ rule that fired). Deriving it
    # from the decision token alone explained a prompt-injection block as "confidence too low".
    rationale = entry.get("rationale") or {
        "PASSTHROUGH": "Model confidence above safety threshold; response released without review.",
        "FLAG": "Confidence above threshold but flagged for compliance review.",
        "REASK": "Confidence below threshold; customer was asked to clarify.",
        "ESCALATE": "Confidence too low OR safety intent — human review required.",
    }.get(decision, "Decision rationale not recorded.")
    intent_catalog_hit = next((i for i in s._INTENT_CATALOG if i["name"] == intent), None)

    # Confidentiality: the trail keeps the substantive answer for the model-risk reviewer even
    # when the guard held it back from the customer. Whether it WAS held back is a fact the
    # pipeline records (server._answer_withheld_from_customer) — it cannot be re-derived from
    # the decision token alone, because it differs per path (a fresh ESCALATE releases the
    # answer; a cached one does not).
    #
    # But it must FAIL CLOSED. The audit deque is rehydrated from persistent SQLite at every
    # boot (state/audit._audit_restore_from_db), and entries written before this flag existed
    # carry the substantive `answer` with NO flag. Defaulting a missing flag to "released"
    # handed those answers straight back — re-opening, for all historical data, the exact leak
    # this surface exists to close. When the fact wasn't recorded, DERIVE it (same rule the
    # pipeline uses) instead of assuming the answer was released.
    withheld = _was_withheld(entry)
    answer_preview = _WITHHELD_MARKER if withheld else (entry.get("answer") or "")[:200]
    # An output-DQ block: the customer got only the marker, and the model's real output sits in
    # blocked_answer. Say so plainly rather than presenting the marker as "the answer".
    blocked = bool(entry.get("blocked_answer"))
    if blocked:
        withheld = True
        answer_preview = _BLOCKED_MARKER
    return {
        "seq": entry.get("seq"),
        "ts": entry.get("ts"),
        "query_masked": entry.get("query"),
        "query_was_masked": entry.get("query_was_masked", False),
        "pii_count": entry.get("pii_count", 0),
        "intent": intent,
        "intent_family": intent_catalog_hit["family"] if intent_catalog_hit else None,
        "intent_description": intent_catalog_hit["description"] if intent_catalog_hit else None,
        "agent": intent_catalog_hit["agent"] if intent_catalog_hit else None,
        "confidence": entry.get("confidence"),
        "decision": decision,
        "decision_rationale": rationale,
        "answer_preview": answer_preview,
        "answer_withheld": withheld,
        "channel": entry.get("channel"),
        "tier": entry.get("tier"),
        "cost_cents": entry.get("cost_cents"),
        "from_cache": entry.get("from_cache", False),
        "chain": chain,
        "lgpd_basis": (
            "Provided under LGPD Art. 20 (right to an explanation regarding "
            "automated decisions). The customer may request human review."
        ),
    }


@router.get("/audit/explain/{seq}")
def audit_explain_by_seq(seq: int) -> dict[str, Any]:
    """LGPD Art. 20 explanation addressed by hash-chain ``seq``."""
    s = _server()
    target: dict[str, Any] | None = None
    for entry in list(s._AUDIT):
        if entry.get("seq") == seq:
            target = entry
            break
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"seq={seq} not found in in-memory audit window "
                f"(window may have rotated)"
            ),
        )
    return _explain_entry(target)


@router.post("/audit/tamper-test")
def audit_tamper_test(
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Demonstrate tamper detection by mutating one entry and re-verifying.

    Bridge hub connection: pairs with the "verify chain" button in the
    dashboard. Picks the middle audit entry, swaps its ``query`` field to
    a known canary, re-hashes the window, records the failure point, then
    restores the original value so subsequent verifies succeed again.
    """
    s = _server()
    snapshot = list(s._AUDIT)
    if not snapshot:
        raise HTTPException(
            status_code=409,
            detail="Audit window is empty — cannot demo tamper. Fire a /query first.",
        )
    idx = len(snapshot) // 2
    target = snapshot[idx]
    # The chain hash covers the entry's ENTIRE key set, so "restoring" a key that was never
    # there (governance.*/drift/settings entries carry no "query") would leave a `query: None`
    # behind and break verify FOREVER — the opposite of what this demo proves. Remember
    # whether the key existed and pop it back out if it didn't.
    had_query = "query" in target
    original_query = target.get("query")
    tampered_query = "[TAMPERED BY tamper-test endpoint — should fail verify]"

    before = audit_verify()
    target["query"] = tampered_query
    after = audit_verify()
    if had_query:
        target["query"] = original_query
    else:
        target.pop("query", None)
    restored_check = audit_verify()
    return {
        "demo": "audit_tamper_test",
        "target_seq": target.get("seq"),
        "original_query": original_query,
        "tampered_query": tampered_query,
        "verify_before_tamper": {
            "valid": before["valid"],
            "checked": before["checked"],
        },
        "verify_during_tamper": {
            "valid": after["valid"],
            "checked": after["checked"],
            "first_failure": after.get("first_failure"),
        },
        "restored": True,
        "verify_after_restore": {
            "valid": restored_check["valid"],
            "checked": restored_check["checked"],
        },
        "note": (
            "Demo only — the entry was mutated in memory, then restored. "
            "Real production tampering would persist; the chain verifier "
            "would surface the same first_failure under audit replay."
        ),
    }


def _human_age(ts: float | None) -> str:
    if not ts:
        return "unknown"
    age = time.time() - ts
    if age < 60:
        return f"{int(age)}s ago"
    if age < 3600:
        return f"{int(age / 60)}m ago"
    if age < 86400:
        return f"{int(age / 3600)}h ago"
    return f"{int(age / 86400)}d ago"


@router.get("/audit/replay/{seq}")
def audit_replay(seq: int) -> dict[str, Any]:
    """Deterministically replay a logged query through classify + guard.

    Bridge hub connection: lets SR 11-7 reviewers spot-check whether the
    classifier still routes a previously-seen query the same way.
    """
    s = _server()
    target: dict[str, Any] | None = None
    for entry in list(s._AUDIT):
        if entry.get("seq") == seq:
            target = entry
            break
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"seq={seq} not found in in-memory audit window (window seq range may have rotated)",
        )
    stored_query = target.get("query") or ""
    replay_intent, replay_conf = s.classify_intent(stored_query)
    replay_decision, replay_reason = s.apply_guard(replay_conf, intent=replay_intent)
    original_intent = target.get("intent")
    original_decision = target.get("decision")
    # Replay only makes sense for entries that went through the /query intent classifier.
    # Synthetic entries (e.g. visibility_collection) never came from classify_intent, so
    # replaying them through it would ALWAYS "deviate" — a false determinism alarm. Flag
    # them as not-replayable instead of reporting a misleading deviation.
    classifier_intents = {str(e.get("name")) for e in s._INTENT_CATALOG}
    replayable = bool(original_intent) and str(original_intent) in classifier_intents
    deterministic: bool | None = (
        ((replay_intent == original_intent) and (replay_decision == original_decision))
        if replayable
        else None
    )
    original_ts = target.get("ts")
    now_ts = time.time()
    return {
        "seq": seq,
        "ts": original_ts,
        "original_processed_at": original_ts,
        "replayed_at": now_ts,
        "age_seconds": (now_ts - original_ts) if original_ts else None,
        "replay_against_version": {
            "api_version": "0.2.0",
            "model": "fake-demo-v1",
            "prompt_template_hash": s._PROMPT_FINGERPRINT,
            "corpus_version": s._CORPUS_FINGERPRINT,
            "dq_input_rules": len(s._DQ_INPUT.rules),
        },
        "query_masked": stored_query,
        "query_was_masked": target.get("query_was_masked", False),
        "pii_count": target.get("pii_count", 0),
        "original": {
            "intent": original_intent,
            "confidence": target.get("confidence"),
            "decision": original_decision,
        },
        "replay": {
            "intent": replay_intent,
            "confidence": round(replay_conf, 3),
            "decision": replay_decision,
            "reason": replay_reason,
        },
        "replayable": replayable,
        "deterministic": deterministic,
        "note": (
            (
                "Replay re-runs classify_intent + apply_guard on the stored "
                "masked query against the CURRENT code. The LLM and RAG layers "
                "are NOT re-invoked. A non-deterministic result means the "
                "classifier or guard logic changed between original processing "
                f"({_human_age(original_ts)}) and now."
            )
            if replayable
            else (
                f"intent={original_intent!r} was not produced by the /query intent "
                "classifier (e.g. a visibility-collection or system entry), so "
                "replay-through-classify does not apply — this is not a determinism signal."
            )
        ),
    }


@router.get("/explain/{audit_index}")
def explain(audit_index: int) -> dict[str, Any]:
    """Return the rationale for one audit entry (LGPD Art. 20-aligned)."""
    s = _server()
    all_newest_first = list(reversed(list(s._AUDIT)))
    if audit_index < 0 or audit_index >= len(all_newest_first):
        raise HTTPException(
            status_code=404,
            detail=(f"audit_index={audit_index} out of range [0, {len(all_newest_first) - 1}]"),
        )
    entry = all_newest_first[audit_index]
    # Same single implementation as /audit/explain/{seq} — this endpoint used to duplicate it
    # and so kept leaking the withheld answer, stamping LGPD Art. 20 on operational events and
    # stating the wrong reason for rule-based blocks long after the other one was fixed.
    base = _explain_entry(entry)
    if base.get("kind") == "governance":
        return {"audit_index": audit_index, **base}

    intent = base["intent"]
    intent_explanation = {
        "crisis": "Crisis/self-harm signals detected. Routed to human + CVV 188.",
        "social_engineering": "Pattern matches the 'fake agent' scam. Routed to antifraud.",
        "illegal_activity": "Request for guidance on illicit conduct refused; redirect to RFB.",
        "aml_review": "Operation matches AML/PCD trigger (cash >= R$30k). Compliance review.",
        "card_fraud": "Fraud markers detected. Antifraud team engaged.",
        "non_pt": "Query was not in Portuguese. Customer asked to rephrase in PT.",
    }.get(intent)
    # Legacy shape: index-addressed + its own intent_explanation copy, everything else
    # (rationale, withheld answer, LGPD basis) comes from the shared explainer.
    return {
        "audit_index": audit_index,
        **base,
        "intent_explanation": intent_explanation,
    }


@router.delete("/audit")
def rotate_audit(
    operator: str = "",
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Rotate the in-memory audit window (demo).

    Bridge hub connection: in-memory equivalent of the production
    audit log rotation. Records the rotation itself as the first entry
    of the new window so the audit-of-the-audit trail is unbroken — now
    stamped with the acting operator so the (ungoverned) rotation is at
    least attributed on the chain.
    """
    operator = principal["sub"] if principal else operator
    s = _server()
    rotated = len(s._AUDIT)
    s._AUDIT.clear()
    now_iso = datetime.now(UTC).isoformat()
    marker = s._audit_append(
        {
            "ts": time.time(),
            # An OPERATOR action, not an automated decision about a data subject. Without
            # this key the explainer routed it to the LGPD Art. 20 shape and told an auditor
            # a human's rotation was "an automated decision about a customer".
            "event": "audit.rotation",
            "query": "[audit window rotated]",
            "intent": "audit_rotation",
            "operator": operator or "unknown",
            "confidence": 1.0,
            "decision": "PASSTHROUGH",
            "answer": (
                f"Previous window archived. {rotated} entries removed "
                f"from in-memory store. In production, those entries "
                f"would have been pushed to cold storage with the BCB "
                f"4893 5-year retention policy applied."
            ),
            "customer_id": "system",
            "channel": "system",
            "from_cache": False,
            "tier": "system",
            "cost_cents": 0.0,
            "query_was_masked": False,
            "pii_count": 0,
        }
    )
    return {
        "status": "rotated",
        "rotated_count": rotated,
        "new_window_started_at": now_iso,
        "first_seq_new_window": marker["seq"],
        "prev_hash_chained_from": marker["prev_hash"],
    }


__all__ = ["router"]
