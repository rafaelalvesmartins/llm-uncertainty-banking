"use client";

import { useState, type ReactNode } from "react";

/**
 * Collapsible section — the "keep advanced/details out of the way" pattern used to
 * keep dense console pages simple by default (mirrors the per-page <details> glossaries
 * and the Policies "Advanced" disclosure). Self-contained: the caret rotates on open
 * without any global CSS.
 */
export default function Disclosure({
  title,
  hint,
  children,
  defaultOpen = false,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      style={{ border: "1px solid var(--bc-border)", borderRadius: 10, background: "var(--bc-surface)" }}
    >
      <summary
        style={{
          cursor: "pointer",
          listStyle: "none",
          padding: "12px 16px",
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 14,
          fontWeight: 600,
          color: "var(--bc-text)",
        }}
      >
        <span
          aria-hidden
          style={{
            color: "var(--bc-text-mute)",
            fontSize: 12,
            display: "inline-block",
            transition: "transform 0.15s ease",
            transform: open ? "rotate(90deg)" : "none",
          }}
        >
          ▸
        </span>
        {title}
        {hint && <span style={{ fontWeight: 400, fontSize: 12, color: "var(--bc-text-mute)" }}>· {hint}</span>}
      </summary>
      <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "4px 12px 14px" }}>{children}</div>
    </details>
  );
}
