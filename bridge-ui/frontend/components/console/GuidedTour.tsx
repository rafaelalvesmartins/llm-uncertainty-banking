"use client";

import { useEffect, useRef, useState } from "react";

import GovernanceGlossary from "@/components/console/GovernanceGlossary";

// Guided walkthrough — a floating "coach" that steps through the key pages, navigating
// to each and explaining what the operator is looking at + what to try. Opened by
// dispatching a `bridge:start-tour` event (from the topbar or the golden-path card), so
// any trigger can launch it without prop-drilling. Page-level (robust) rather than a
// pixel-spotlight that would break across navigation.
const TOUR: { view: string; title: string; body: string; glossary?: string[] }[] = [
  { view: "dashboard", title: "1 · The overview", body: "Your live snapshot. Every number here — the tiles, the funnel, the charts — is clickable and opens the exact records behind it." },
  { view: "flow", title: "2 · Ask the AI", body: "Type a customer message (or pick an example) and watch it travel the safety pipeline, ending in a decision with the reason why." },
  { view: "policies", title: "3 · Set the rules", body: "Decide what each channel is allowed to do, and tune how cautious the assistant is. Risky changes go through approval." },
  { view: "audit", title: "4 · The proof", body: "Every decision is kept in a tamper-proof log. Click any row to see why the AI decided that." },
  { view: "governance", title: "5 · Two-person control", body: "No change goes live until different people propose it, approve it and apply it — so nobody can change a live system alone. Banks call this “four-eyes” (the rule book name is SR 11-7).", glossary: ["Four-eyes", "Segregation of duties"] },
];

function go(view: string): void {
  if (typeof window === "undefined") return;
  window.location.hash = view;
  window.dispatchEvent(new CustomEvent("bridge:goto", { detail: { view } }));
}

export default function GuidedTour() {
  const [step, setStep] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);

  // Open on the global event; close on Escape.
  useEffect(() => {
    const open = () => { prevFocusRef.current = document.activeElement as HTMLElement | null; setStep(0); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setStep(null); };
    window.addEventListener("bridge:start-tour", open);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("bridge:start-tour", open);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  // Non-modal, so no focus trap — just move focus into the panel on open and
  // restore it to the trigger ("? Tour" chip) on close.
  useEffect(() => {
    if (step !== null) containerRef.current?.focus();
    else prevFocusRef.current?.focus?.();
  }, [step]);

  // Navigate to the current step's page whenever it changes.
  useEffect(() => {
    if (step !== null && TOUR[step]) go(TOUR[step].view);
  }, [step]);

  if (step === null) return null;
  const s = TOUR[step];
  const last = step === TOUR.length - 1;

  return (
    <div
      ref={containerRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="false"
      aria-label="Guided tour"
      style={{
        position: "fixed",
        right: 18,
        bottom: 18,
        zIndex: 1000,
        width: 320,
        maxWidth: "calc(100vw - 36px)",
        background: "var(--bc-surface)",
        border: "1px solid var(--bc-accent)",
        borderRadius: 12,
        boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
        padding: "14px 16px",
      }}
    >
      <div role="status" aria-live="polite">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
          <strong style={{ fontSize: 14, color: "var(--bc-text)" }}>{s.title}</strong>
          <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>Step {step + 1} of {TOUR.length}</span>
        </div>
        <p style={{ fontSize: 12.5, color: "var(--bc-text-dim)", lineHeight: 1.5, margin: "0 0 12px" }}>{s.body}</p>
      </div>
      {s.glossary && (
        <div style={{ margin: "0 0 12px" }}>
          <GovernanceGlossary terms={s.glossary} />
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button
          type="button"
          className="bc-btn ghost"
          onClick={() => setStep((v) => (v != null && v > 0 ? v - 1 : v))}
          disabled={step === 0}
          style={{ fontSize: 12 }}
        >
          Back
        </button>
        <span style={{ flex: 1 }} />
        <button type="button" className="bc-btn ghost" onClick={() => setStep(null)} style={{ fontSize: 12 }}>
          Close
        </button>
        <button
          type="button"
          className="bc-btn"
          onClick={() => (last ? setStep(null) : setStep((v) => (v != null ? v + 1 : v)))}
          style={{ fontSize: 12 }}
        >
          {last ? "Done" : "Next →"}
        </button>
      </div>
    </div>
  );
}
