"use client";

import { useEffect, useState } from "react";

/**
 * Hero value-counter strip. Leads with the RISK number a model-risk buyer cares
 * about (unsafe/overconfident answers stopped), then volume and auto-resolution,
 * and demotes the cost figure to last — so the first few seconds read as a
 * model-risk console, not a cost-deflection dashboard.
 *
 * Reads /api/metrics (decisions + total) and /api/cache (cost_saved_cents) on
 * the same refreshKey cadence as the rest of the dashboard. cost_saved_cents
 * is in US-cents in the backend; the demo frames it as R$ for the audience.
 */

interface Props {
  refreshKey: number;
}

interface Metrics {
  queries_total: number;
  decisions: Record<string, number>;
}

export default function ValueStrip({ refreshKey }: Props) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [costSavedCents, setCostSavedCents] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/api/metrics", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
      fetch("/api/cache", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([m, c]) => {
        if (cancelled) return;
        // /api/metrics is proxied as { metrics, health, audit } in the bundled
        // route but as a flat object from the backend; accept either shape.
        const mm = m?.metrics ?? m;
        if (mm && typeof mm.queries_total === "number") setMetrics(mm);
        if (c && typeof c.cost_saved_cents === "number") setCostSavedCents(c.cost_saved_cents);
      })
      .catch(() => {
        /* swallow — strip just keeps its prior values */
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const loaded = metrics !== null;
  const total = metrics?.queries_total ?? 0;
  const passthrough = metrics?.decisions?.PASSTHROUGH ?? 0;
  const escalate = metrics?.decisions?.ESCALATE ?? 0;
  const autoPct = total > 0 ? Math.round((passthrough / total) * 100) : 0;

  return (
    <div className="value-strip" role="note" aria-label="Value summary">
      <div
        className="value-cell"
        title="Answers the guard held back for a human because they were too risky or too low-confidence (ESCALATE) — the model-risk payoff: the system stays quiet when it isn't sure."
      >
        <div className={`value-num${loaded ? " warn" : ""}`}>{loaded ? escalate : "—"}</div>
        <div className="value-label">unsafe answers stopped</div>
      </div>
      <div className="value-cell">
        <div className="value-num">{loaded ? total : "—"}</div>
        <div className="value-label">decisions logged</div>
      </div>
      <div
        className="value-cell"
        title="Responses passed directly by the guard (PASSTHROUGH). A low value reflects the current conservative threshold — lower 'How cautious the AI is' in Config to pass more responses without review."
      >
        <div className={`value-num${loaded && autoPct > 0 ? " ok" : ""}`}>{loaded ? `${autoPct}%` : "—"}</div>
        <div className="value-label">auto-resolved</div>
      </div>
      <div className="value-cell">
        <div className={`value-num${costSavedCents ? " ok" : ""}`}>
          {costSavedCents !== null ? `R$ ${(costSavedCents / 100).toFixed(2)}` : "—"}
        </div>
        <div className="value-label">saved by cache</div>
      </div>
    </div>
  );
}
