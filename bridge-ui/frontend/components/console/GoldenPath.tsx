"use client";

import { useEffect, useState } from "react";

// Golden-path onboarding strip for the Dashboard: connects the end-to-end story
// (ask → decide → see → prove) as four clickable steps, plus a one-click live demo
// that runs a vivid question through the real pipeline and opens it in the audit log.
// Dismissible (persisted in localStorage) so it doesn't nag returning operators.
const STEPS: { n: number; view: string; title: string; body: string }[] = [
  { n: 1, view: "flow", title: "Ask", body: "A customer asks the assistant a question." },
  { n: 2, view: "policies", title: "Decide", body: "The safety guard answers, flags, re-asks, or sends it to a human." },
  { n: 3, view: "dashboard", title: "See", body: "Every question is counted and charted right here." },
  { n: 4, view: "audit", title: "Prove", body: "Every decision is saved to a tamper-proof, append-only audit trail — a record nobody can quietly edit or delete. Click any entry for the reason why, or run “Prove tamper detection” to watch the chain catch an edit live." },
  { n: 5, view: "governance", title: "Govern", body: "No change goes live until a different person proposes, approves, and applies it — two-person control (four-eyes / SR 11-7). Download the signed evidence package auditors can verify." },
];

function go(view: string): void {
  if (typeof window === "undefined") return;
  window.location.hash = view;
  window.dispatchEvent(new CustomEvent("bridge:goto", { detail: { view } }));
}

export default function GoldenPath() {
  const [hidden, setHidden] = useState(true);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setHidden(window.localStorage.getItem("bridge:goldenPathHidden") === "1");
  }, []);

  // Recoverable after Dismiss: starting the tour ("? Tour" / "Take the tour")
  // clears the persisted flag and brings the 4-step guide back.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const restore = () => {
      window.localStorage.removeItem("bridge:goldenPathHidden");
      setHidden(false);
    };
    window.addEventListener("bridge:start-tour", restore);
    return () => window.removeEventListener("bridge:start-tour", restore);
  }, []);

  if (hidden) return null;

  function dismiss() {
    if (typeof window !== "undefined") window.localStorage.setItem("bridge:goldenPathHidden", "1");
    setHidden(true);
  }

  async function runSample() {
    setRunning(true);
    setNote(null);
    setFailed(false);
    try {
      const r = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: "meu cartão foi clonado e fizeram compras que eu não reconheço",
          channel: "app",
          customer_id: "demo-tour",
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const dec = String(d.decision || "");
      setNote(`Sent a cloned-card report → ${dec}. Opening the log…`);
      if (typeof window !== "undefined") {
        // Filter the audit view to whatever the pipeline actually decided (on a
        // real LLM this may be FLAG/REASK, not ESCALATE) so the just-created
        // entry is visible, not hidden behind a hardcoded filter.
        if (dec) {
          window.sessionStorage.setItem("bridge:auditFilter", JSON.stringify({ decision: dec }));
        } else {
          window.sessionStorage.removeItem("bridge:auditFilter");
        }
      }
      go("audit");
    } catch (e) {
      setFailed(true);
      setNote(`Could not run the sample (${e instanceof Error ? e.message : String(e)}). The demo backend may be offline — try again, or skip this for now.`);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="bc-card" style={{ borderColor: "var(--bc-accent)", marginBottom: 16 }}>
      <div className="bc-card-h">
        <h2 style={{ fontSize: 15 }}>How Bridge works — in 4 steps</h2>
        <button type="button" className="bc-btn ghost" onClick={dismiss} style={{ fontSize: 12 }} title="Hide this guide">
          Dismiss
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "stretch" }}>
        {STEPS.map((s, i) => (
          <div key={s.n} style={{ display: "flex", alignItems: "stretch", gap: 8, flex: "1 1 180px" }}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => go(s.view)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(s.view); } }}
              title={`Open ${s.title}`}
              style={{ flex: 1, cursor: "pointer", background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 10, padding: "10px 12px" }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ width: 20, height: 20, borderRadius: 999, background: "var(--bc-accent)", color: "#0b1220", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{s.n}</span>
                <strong style={{ fontSize: 13 }}>{s.title}</strong>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--bc-text-dim)", lineHeight: 1.45 }}>{s.body}</div>
            </div>
            {i < STEPS.length - 1 && <span aria-hidden style={{ alignSelf: "center", color: "var(--bc-text-mute)" }}>→</span>}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button type="button" className="bc-btn" onClick={runSample} disabled={running} style={{ fontSize: 13 }}>
          {running ? "Running…" : "▶ Run a sample question"}
        </button>
        <button
          type="button"
          className="bc-btn ghost"
          onClick={() => { if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("bridge:start-tour")); }}
          style={{ fontSize: 13 }}
        >
          Take the tour
        </button>
        <span style={{ fontSize: 12, color: failed ? "var(--bc-block-line)" : "var(--bc-text-mute)" }}>
          {note ?? "Sends a cloned-card fraud report through the live pipeline and opens it in the audit log."}
        </span>
        {failed && (
          <>
            <button type="button" className="bc-btn" onClick={runSample} disabled={running} style={{ fontSize: 13 }} title="Run the same sample question again">
              Retry
            </button>
            <button type="button" className="bc-btn ghost" onClick={() => { setFailed(false); setNote(null); }} style={{ fontSize: 13 }} title="Skip the sample and keep going">
              Skip
            </button>
          </>
        )}
      </div>
    </div>
  );
}
