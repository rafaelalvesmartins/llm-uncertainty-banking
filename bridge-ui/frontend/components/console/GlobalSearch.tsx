"use client";

import { useState } from "react";

// Console-wide "go to" bar: jump straight to a customer's Sessions, the audit trail
// filtered by text, or a specific audit entry by #seq — from anywhere. Writes the
// target page's sessionStorage filter (so it also survives a refresh) and fires a
// 'bridge:goto' event so the jump works even when already on the destination page.
type Scope = "customers" | "audit";

function goto(view: string): void {
  window.location.hash = view;
  window.dispatchEvent(new CustomEvent("bridge:goto", { detail: { view } }));
}

export default function GlobalSearch() {
  const [scope, setScope] = useState<Scope>("customers");
  const [q, setQ] = useState("");

  function submit() {
    const v = q.trim();
    if (!v || typeof window === "undefined") return;
    const seq = v.match(/^#?(\d+)$/);
    if (seq) {
      // A bare number / #123 always means "that audit entry", whatever the scope.
      window.sessionStorage.setItem("bridge:auditFocusSeq", seq[1]);
      // Drop any persisted filter so it can't hide the focused entry.
      window.sessionStorage.removeItem("bridge:auditFilter");
      goto("audit");
    } else if (scope === "audit") {
      window.sessionStorage.setItem("bridge:auditFilter", JSON.stringify({ q: v }));
      goto("audit");
    } else {
      // Customer scope: Sessions folded into Audit's "By customer" view. Set the
      // view flag + go to Audit directly (goto("audit") fires Auditoria's onGoto
      // even when already on the tab; it reads bridge:auditView → by-customer,
      // then the embedded SessionsPanel consumes bridge:sessionFilter on mount).
      window.sessionStorage.setItem("bridge:sessionFilter", JSON.stringify({ search: v }));
      window.sessionStorage.setItem("bridge:auditView", "by-customer");
      goto("audit");
    }
    setQ("");
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
      <span style={{ fontSize: 12, color: "var(--bc-text-mute)" }}>🔎 Go to</span>
      <select
        className="bc-input"
        value={scope}
        onChange={(e) => setScope(e.target.value as Scope)}
        aria-label="search scope"
        style={{ fontSize: 12, padding: "4px 6px" }}
      >
        <option value="customers">a customer</option>
        <option value="audit">the audit trail</option>
      </select>
      <input
        className="bc-input"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        placeholder={scope === "customers" ? "customer id…  (or #123 for an audit entry)" : "search text…  (or #123 for an entry)"}
        aria-label="global search"
        style={{ fontSize: 12, padding: "4px 8px", flex: 1, minWidth: 220 }}
      />
      <button type="button" className="bc-btn" onClick={submit} disabled={!q.trim()} style={{ fontSize: 12 }}>
        Go
      </button>
    </div>
  );
}
