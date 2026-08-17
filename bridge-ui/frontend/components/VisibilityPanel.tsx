"use client";

import { useCallback, useEffect, useState } from "react";
import StateBadge from "@/components/StateBadge";
import { apiErrorText } from "@/lib/apiError";
import { decisionLabel } from "@/components/console/types";

interface Mention {
  entity: string;
  mentioned: boolean;
  position: number | null;
  sentiment: string;
}
interface Result {
  query_id: string;
  query: string;
  model: string;
  is_real_model?: boolean;
  answer: string;
  mentions: Mention[];
  confidence: number;
  decision: string;
  audit_seq: number;
  audit_hash: string;
}
interface EntityMetric {
  entity: string;
  mentions: number;
  presence_pct: number;
  share_of_voice: number;
  avg_position: number | null;
}
interface RunData {
  ts: number | null;
  adapter: string;
  queries_run: number;
  results: Result[];
  metrics: { entities: EntityMetric[]; total_mentions: number; queries: number };
}
interface Config {
  queries: { id: string; text: string }[];
  entities: string[];
  own_brand: string;
  active_adapter: string;
  available_adapters: string[];
  real_adapters: string[];
  schedule_every_s?: number;
  schedule_every_minutes?: number;
  gaps: string[];
}
interface Recommendation {
  query_id: string;
  query: string;
  own_brand_state: string;
  gap: number;
  volume_weight: number;
  confidence: number;
  score: number;
  evidence: string;
  action: string;
}
interface Draft {
  id: number;
  query: string;
  text: string;
  confidence: number;
  decision: string;
  status: string;
  publishable: boolean;
  approved_by: string | null;
}

/**
 * Bloco B — AI Visibility + intelligence, with lub instrumentation.
 *
 * Run collections (guard + audit chain per datapoint) → Share-of-Voice,
 * recommendations (B3, volume×gap×confidence), and content drafts gated by the
 * guard (B4: FLAG/ESCALATE blocked, PASSTHROUGH → explicit human approval,
 * never auto-published). Real adapters (B1) activate only with an API key;
 * the offline fake is the default. History (B2) is a SQLite time series.
 */
export default function VisibilityPanel() {
  const [config, setConfig] = useState<Config | null>(null);
  const [run, setRun] = useState<RunData | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [history, setHistory] = useState<{ ts: number; share_of_voice: Record<string, number> }[]>([]);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newPrompt, setNewPrompt] = useState("");
  const [newBrand, setNewBrand] = useState("");

  const refresh = useCallback(async () => {
    const [cfg, res, rec, cont, hist] = await Promise.all([
      fetch("/api/visibility/config", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
      fetch("/api/visibility/results", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
      fetch("/api/visibility/recommendations", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
      fetch("/api/visibility/content", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
      fetch("/api/visibility/history", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
    ]);
    if (cfg && !cfg.error) setConfig(cfg);
    if (res && !res.error) setRun(res);
    if (rec && !rec.error) setRecs(rec.recommendations || []);
    if (cont && !cont.error) setDrafts(cont.drafts || []);
    if (hist && !hist.error) setHistory(hist.runs || []);
  }, []);

  useEffect(() => {
    refresh().catch(() => setError("backend unreachable"));
  }, [refresh]);

  async function runCollection() {
    setRunning(true);
    setError(null);
    try {
      const r = await fetch("/api/visibility/run", { method: "POST" });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
        return;
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  // Add a monitoring prompt / a competitor brand — direct config tuning via the existing
  // PUT (not a governed change; these are operational settings, like the adapter choice).
  async function addPrompt() {
    const text = newPrompt.trim();
    if (!text || !config) return;
    setBusy("add-prompt");
    setError(null);
    try {
      const r = await fetch("/api/visibility/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ queries: [...config.queries.map((q) => q.text), text] }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
      } else {
        setNewPrompt("");
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function addBrand() {
    const name = newBrand.trim();
    if (!name || !config) return;
    setBusy("add-brand");
    setError(null);
    try {
      const r = await fetch("/api/visibility/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entities: [...config.entities, name] }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
      } else {
        setNewBrand("");
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function setSchedule(everyMinutes: number) {
    setBusy("schedule");
    setError(null);
    try {
      const r = await fetch("/api/visibility/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ every_minutes: everyMinutes }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function selectAdapter(name: string) {
    setBusy("adapter");
    setError(null);
    try {
      // A rejected adapter switch (e.g. real adapter with no API key) used to revert
      // silently — surface the reason instead of letting the <select> snap back mute.
      const r = await fetch("/api/visibility/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_adapter: name }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function makeDraft(queryId: string) {
    setBusy(`draft:${queryId}`);
    setError(null);
    try {
      const r = await fetch("/api/visibility/content/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query_id: queryId }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function approve(id: number) {
    setBusy(`approve:${id}`);
    setError(null);
    try {
      const r = await fetch(`/api/visibility/content/${id}/approve`, { method: "POST" });
      if (!r.ok) {
        const d = await r.json().catch(() => null);
        setError(apiErrorText(d, r.status));
      }
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  const decisionClass = (d: string) => `badge ${d.toLowerCase()}`;

  return (
    <div className="card card--wide">
      <h2>
        AI Visibility &amp; Intelligence
        <StateBadge feature="ai-visibility" />
        <button
          type="button"
          className="link-btn"
          onClick={runCollection}
          disabled={running || !config}
          title="Checks how often the AI assistant mentions your bank when customers ask common questions"
          style={{ marginLeft: 8 }}
        >
          {running ? "collecting…" : "run collection"}
        </button>
        <select
          value={String(config?.schedule_every_minutes ?? 0)}
          onChange={(e) => setSchedule(Number(e.target.value))}
          disabled={busy === "schedule" || !config}
          title="Run collection automatically on a schedule — applies at runtime, no restart"
          aria-label="Collection schedule"
          style={{ marginLeft: 8, fontSize: 12 }}
        >
          {![0, 5, 15, 60].includes(config?.schedule_every_minutes ?? 0) && (
            <option value={String(config?.schedule_every_minutes ?? 0)}>
              auto every {config?.schedule_every_minutes} min
            </option>
          )}
          <option value="0">schedule: off</option>
          <option value="5">auto every 5 min</option>
          <option value="15">auto every 15 min</option>
          <option value="60">auto every 60 min</option>
        </select>
      </h2>

      <p style={{ fontSize: 12.5, color: "var(--bc-text-mute)", margin: "0 0 12px", lineHeight: 1.55 }}>
        <strong style={{ color: "var(--bc-text)" }}>What this does:</strong>{" "}
        {"This page checks how often AI chat assistants name your bank versus competitors when customers ask common questions — a brand-visibility scoreboard. It then suggests, and helps you draft, content to improve your standing. Nothing is ever published automatically: a person must review and approve every draft first."}
      </p>

      {error && !config ? (
        <div className="empty">Backend unreachable ({error}).</div>
      ) : !config ? (
        <div className="empty">loading visibility configuration...</div>
      ) : (
        <>
          {error && <div className="warn" style={{ fontSize: 12, marginBottom: 8 }}>⚠ {error}</div>}

          <div className="vis-config muted">
            <strong>{config.queries.length}</strong> prompts ·{" "}
            <strong>{config.entities.length}</strong> brands · own brand{" "}
            <code>{config.own_brand}</code> · AI model{" "}
            <select
              aria-label="AI model adapter"
              value={config.active_adapter}
              onChange={(e) => selectAdapter(e.target.value)}
              disabled={busy === "adapter"}
              style={{ fontSize: 11, padding: "1px 4px" }}
            >
              {config.available_adapters.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>{" "}
            {config.real_adapters.includes(config.active_adapter) ? (
              <span className="state-badge live" title="real model (API key present)">real model</span>
            ) : (
              <span className="state-badge mock" title="canned responses, no real model">simulated responses</span>
            )}
          </div>

          {/* Add a prompt to track / a competitor brand (direct config tuning, like the adapter). */}
          <div className="vis-config" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
            <input
              value={newPrompt}
              onChange={(e) => setNewPrompt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addPrompt()}
              placeholder="add a prompt to track…"
              aria-label="add a monitoring prompt"
              style={{ fontSize: 11, padding: "2px 6px", flex: 1, minWidth: 180 }}
            />
            <button type="button" className="link-btn" onClick={addPrompt} disabled={busy === "add-prompt" || !newPrompt.trim()} style={{ fontSize: 11 }}>
              {busy === "add-prompt" ? "adding…" : "＋ prompt"}
            </button>
            <input
              value={newBrand}
              onChange={(e) => setNewBrand(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addBrand()}
              placeholder="add a competitor…"
              aria-label="add a competitor brand"
              style={{ fontSize: 11, padding: "2px 6px", minWidth: 140 }}
            />
            <button type="button" className="link-btn" onClick={addBrand} disabled={busy === "add-brand" || !newBrand.trim()} style={{ fontSize: 11 }}>
              {busy === "add-brand" ? "adding…" : "＋ competitor"}
            </button>
            <span className="muted" style={{ fontSize: 10 }}>then run a collection to score them</span>
          </div>

          {/* Share-of-Voice */}
          {run && run.results.length > 0 && (
            <div className="vis-sov">
              <div className="vis-section-label">
                Brand mentions in AI answers {run.ts && `· collected ${new Date(run.ts * 1000).toLocaleTimeString()}`}
                {history.length > 1 && <span className="muted"> · {history.length} runs saved</span>}
              </div>
              {run.metrics.entities.map((e) => (
                <div key={e.entity} className="vis-sov-row">
                  <span className="vis-entity">{e.entity}</span>
                  <div className="vis-bar-track" title={`${(e.share_of_voice * 100).toFixed(0)}% share of mentions`}>
                    <div className="vis-bar" style={{ width: `${Math.max(e.share_of_voice * 100, 2)}%` }} />
                  </div>
                  <span className="vis-sov-num">
                    {(e.share_of_voice * 100).toFixed(0)}% of mentions · {(e.presence_pct * 100).toFixed(0)}% presence
                    {e.avg_position !== null && ` · pos ${e.avg_position}`}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Per-question detail (with audit proof) — collapsed by default; technical for most viewers. */}
          {run && run.results.length > 0 && (
            <details className="vis-results">
              <summary className="vis-section-label" style={{ cursor: "pointer" }}>Per-question detail (with audit proof)</summary>
              {run.results.map((r) => (
                <div key={r.query_id} className="vis-result">
                  <div className="vis-result-head">
                    <span className="vis-query">{r.query}</span>
                    <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span className={decisionClass(r.decision)}>{decisionLabel(r.decision)}</span>
                      <span className="muted" style={{ fontSize: 11 }}>conf {(r.confidence * 100).toFixed(0)}%</span>
                    </span>
                  </div>
                  <div className="vis-mentions">
                    {r.mentions.map((m) => (
                      <span
                        key={m.entity}
                        className={`vis-mention ${m.mentioned ? "hit" : "miss"}`}
                        title={m.mentioned ? `position ${m.position}` : "not mentioned"}
                      >
                        {m.mentioned ? `${m.entity} #${m.position}` : m.entity}
                      </span>
                    ))}
                  </div>
                  <div className="vis-audit muted" title="tamper-evident proof for this collection">
                    audit seq #{r.audit_seq} · hash {r.audit_hash.slice(0, 16)}…
                  </div>
                </div>
              ))}
            </details>
          )}

          {/* B3 Recommendations */}
          {recs.length > 0 && (
            <div className="vis-recs">
              <div className="vis-section-label">
                Recommended topics to improve — ranked by impact · brand {config.own_brand}
              </div>
              {recs.map((r) => (
                <div key={r.query_id} className="vis-rec">
                  <div className="vis-rec-head">
                    <span className="vis-query">{r.query}</span>
                    <span className="vis-score" title="volume × gap × confidence">score {r.score}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    state: {r.own_brand_state} · gap {(r.gap * 100).toFixed(0)}% · conf {(r.confidence * 100).toFixed(0)}% · vol {r.volume_weight}
                  </div>
                  <div style={{ fontSize: 12, margin: "3px 0" }}>{r.action}</div>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => makeDraft(r.query_id)}
                    disabled={busy === `draft:${r.query_id}`}
                    title="Generate content draft (passes through the uncertainty guard before it can be approved)"
                  >
                    {busy === `draft:${r.query_id}` ? "generating…" : "generate draft →"}
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* B4 Content drafts — human-gated */}
          {drafts.length > 0 && (
            <div className="vis-content">
              <div className="vis-section-label">
                Suggested content — reviewed before use, never auto-published
              </div>
              {drafts.map((d) => (
                <div key={d.id} className="vis-draft">
                  <div className="vis-draft-head">
                    <span style={{ fontSize: 12, color: "var(--bc-text)" }}>#{d.id} · {d.query}</span>
                    <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span className={decisionClass(d.decision)}>{decisionLabel(d.decision)}</span>
                      <span
                        className={`state-badge ${d.status === "approved" ? "live" : d.status === "blocked" ? "mock" : "static"}`}
                        style={{ marginLeft: 0 }}
                      >
                        {d.status}
                      </span>
                    </span>
                  </div>
                  <div className="vis-answer">{d.text}</div>
                  {d.status === "pending_approval" && (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => approve(d.id)}
                      disabled={busy === `approve:${d.id}`}
                      title="Explicit human approval — queues the draft (does not publish to any external channel)"
                    >
                      {busy === `approve:${d.id}` ? "approving…" : "✓ approve (human)"}
                    </button>
                  )}
                  {d.status === "blocked" && (
                    <span className="muted" style={{ fontSize: 11 }}>
                      blocked by guard ({decisionLabel(d.decision)}) — cannot be approved/published
                    </span>
                  )}
                  {d.status === "approved" && (
                    <span className="ok" style={{ fontSize: 11 }}>
                      ✓ approved by {d.approved_by} · queued (no external publication)
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {!run || run.results.length === 0 ? (
            <div className="empty">No collections yet — click <strong>run collection</strong>.</div>
          ) : null}

          <div className="vis-gaps muted">
            <strong>Demo shape (honest gaps):</strong> {config.gaps.join(" · ")}
          </div>
        </>
      )}
    </div>
  );
}
