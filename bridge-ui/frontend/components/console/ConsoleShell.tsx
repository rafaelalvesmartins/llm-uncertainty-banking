"use client";

import React from "react";
import { useAppContext, OPERATORS } from "@/components/AppContextProvider";
import PendingChangesBadge from "@/components/console/PendingChangesBadge";

export type ViewId =
  | "dashboard"
  | "flow"
  | "connections"
  | "policies"
  | "audit"
  | "observability"
  | "governance"
  | "config";

export interface ViewMeta {
  id: ViewId;
  label: string;
  icon: React.ReactNode;
}

const svg = (children: React.ReactNode): React.ReactNode => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);

// Single source of truth for the rail nav + page view order.
// The `id` is the URL hash slug and matches the label (kept in English so deep-links like /console#flow work).
export const CONSOLE_VIEWS: ViewMeta[] = [
  { id: "dashboard", label: "Dashboard", icon: svg(<><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></>) },
  { id: "flow", label: "Flow", icon: svg(<><path d="M3 12h13" /><path d="M13 6l6 6-6 6" /></>) },
  { id: "connections", label: "Connections", icon: svg(<><circle cx="6" cy="6" r="2.4" /><circle cx="18" cy="6" r="2.4" /><circle cx="12" cy="18" r="2.4" /><path d="M8.2 6.6 15.8 6.6M7.2 7.8 11 16M16.8 7.8 13 16" /></>) },
  { id: "policies", label: "Policies", icon: svg(<path d="M12 3l8 3v5.5c0 4.7-3.3 7.2-8 8.5-4.7-1.3-8-3.8-8-8.5V6z" />) },
  { id: "audit", label: "Audit", icon: svg(<><path d="M4 6h12M4 12h12M4 18h8" /><path d="M15 17l2 2 4-4" /></>) },
  { id: "observability", label: "Observ.", icon: svg(<><circle cx="12" cy="12" r="2.6" /><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /></>) },
  { id: "governance", label: "Governance", icon: svg(<><path d="M3 21h18" /><path d="M5 21V10l7-4.5 7 4.5v11" /><path d="M9.5 21v-5.5h5V21" /></>) },
  { id: "config", label: "Config", icon: svg(<><circle cx="12" cy="12" r="3" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.1 5.1l2.1 2.1M16.8 16.8l2.1 2.1M5.1 18.9l2.1-2.1M16.8 7.2l2.1-2.1" /></>) },
];

// Rail sections — group the views so the mental model is obvious (vs a flat list).
const GROUP_OF: Record<ViewId, string> = {
  dashboard: "Operate", flow: "Operate",
  connections: "Govern", policies: "Govern", governance: "Govern", audit: "Govern",
  observability: "Monitor",
  config: "Setup",
};
const RAIL_GROUPS = ["Operate", "Govern", "Monitor", "Setup"] as const;

interface Props {
  active: ViewId;
  onSelect: (id: ViewId) => void;
  backendName: string;
  backendIsReal: boolean;
  /** Air-gapped profile in force (LUB_LOCAL_ONLY), read from /health. */
  localOnly?: boolean;
  healthy: boolean | null;
  children: React.ReactNode;
}

export default function ConsoleShell({ active, onSelect, backendName, backendIsReal, localOnly, healthy, children }: Props) {
  const current = CONSOLE_VIEWS.find((v) => v.id === active);
  const { operator, setOperator } = useAppContext();
  return (
    <>
      <nav className="bc-rail" aria-label="Console sections">
        <div className="bc-rail-brand">B</div>
        {RAIL_GROUPS.map((g) => (
          <React.Fragment key={g}>
            <div className="bc-rail-group">{g}</div>
            {CONSOLE_VIEWS.filter((v) => GROUP_OF[v.id] === g).map((v) => (
              <button
                key={v.id}
                type="button"
                className={`bc-rail-item ${active === v.id ? "active" : ""}`}
                aria-current={active === v.id ? "page" : undefined}
                onClick={() => onSelect(v.id)}
              >
                {v.icon}
                {v.label}
              </button>
            ))}
          </React.Fragment>
        ))}
      </nav>

      <div className="bc-main">
        <header className="bc-topbar">
          <div>
            <h1>{current?.label ?? "Console"}</h1>
            <div className="bc-sub">Bridge · query → inspection → decision</div>
          </div>
          <div className="bc-topbar-chips">
            <PendingChangesBadge />
            <button
              type="button"
              className="bc-chip"
              onClick={() => window.dispatchEvent(new CustomEvent("bridge:start-tour"))}
              style={{ cursor: "pointer" }}
              title="Take a guided tour of the console"
            >
              ? Tour
            </button>
            <label className="bc-chip" title="Demo operator — assigns change submission/approval/apply. No real auth (phase v6).">
              Operator
              <select
                value={operator}
                onChange={(e) => setOperator(e.target.value)}
                aria-label="Demo operator"
                style={{ background: "var(--bc-surface-2)", border: "1px solid var(--bc-border)", borderRadius: 6, padding: "2px 6px", color: "var(--bc-text)", fontSize: 12, marginLeft: 6 }}
              >
                {OPERATORS.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            {healthy === true ? (
              <>
                <span className="bc-chip"><span className="bc-dot pass" />{backendName}</span>
                <span className="bc-chip">{backendIsReal ? "Real LLM" : "Demo"}</span>
                {/* Which side of the data perimeter this deployment runs on.
                    Only asserted when the library actually enforces it — a
                    perimeter claimed but not enforced is worse than none. */}
                {localOnly === true && (
                  <span
                    className="bc-chip"
                    title={
                      "Air-gapped profile enforced (LUB_LOCAL_ONLY): hosted-API backends refuse to construct, " +
                      "so the objects that could carry a customer prompt off-premises cannot be built. " +
                      "Covers customer prompts — it is not a network firewall."
                    }
                  >
                    <span className="bc-dot pass" />Air-gapped
                  </span>
                )}
              </>
            ) : (
              <span className="bc-chip"><span className="bc-dot block" />— unknown</span>
            )}
            <span className="bc-chip">
              <span className={`bc-dot ${healthy === false ? "block" : "pass"}`} />
              {healthy === false ? "BFF offline" : healthy === true ? "BFF online" : "checking…"}
            </span>
          </div>
        </header>
        {healthy === false && (
          <div role="alert" style={{ background: "var(--bc-block)", color: "var(--bc-block-text)", border: "1px solid var(--bc-block-line)", borderRadius: 6, padding: "8px 14px", margin: "0 16px 10px", fontSize: 13 }}>
            Backend offline — run <code>bridge-ui/start-demo.sh</code> to bring it back.
          </div>
        )}
        <main className="bc-content">{children}</main>
      </div>
    </>
  );
}
