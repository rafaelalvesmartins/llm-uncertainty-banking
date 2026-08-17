"use client";

import { useEffect, useState } from "react";

// Always-visible "something needs a human" indicator in the topbar. Governed changes
// waiting to be approved (pending) or applied (approved) were otherwise invisible until
// you opened the Governance/Connections panels — an operator could miss work that needs
// them. Polls the change ledger; shows an amber chip → Governance when > 0, nothing when
// the queue is clear.
interface ChangesResponse {
  by_status?: Record<string, number>;
  changes?: { status?: string }[];
}

export default function PendingChangesBadge() {
  const [n, setN] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch("/api/governance/changes", { cache: "no-store" })
        .then((r) => (r.ok ? (r.json() as Promise<ChangesResponse>) : null))
        .then((j) => {
          if (cancelled || !j) return;
          const bs = j.by_status;
          const awaiting = bs
            ? (bs.pending ?? 0) + (bs.approved ?? 0)
            : (j.changes ?? []).filter((c) => c.status === "pending" || c.status === "approved").length;
          setN(awaiting);
        })
        .catch(() => { /* keep last count on a transient blip */ });
    };
    load();
    const id = setInterval(() => { if (!document.hidden) load(); }, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (n === 0) return null;

  return (
    <button
      type="button"
      className="bc-chip"
      onClick={() => { if (typeof window !== "undefined") window.location.hash = "governance"; }}
      title="Governed changes waiting to be approved or applied — click to review"
      style={{ cursor: "pointer", borderColor: "var(--bc-flag-line)", color: "var(--bc-flag-text)" }}
    >
      <span className="bc-dot flag" />
      {n} awaiting action
    </button>
  );
}
