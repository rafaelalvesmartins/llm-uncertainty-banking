"use client";

// Shared empty-state affordance: on a fresh backend (zero queries) every data
// surface would otherwise dead-end with a sentence. This adds a one-click route
// to actually produce a query, so the cold-open console is never inert.
export default function AskInFlowLink({ prefix }: { prefix: string }) {
  return (
    <div className="bc-empty">
      {prefix}{" "}
      <button
        type="button"
        className="link-btn"
        onClick={() => {
          if (typeof window === "undefined") return;
          window.location.hash = "flow";
          window.dispatchEvent(new CustomEvent("bridge:goto", { detail: { view: "flow" } }));
        }}
      >
        Ask one in the Flow tab →
      </button>
    </div>
  );
}
