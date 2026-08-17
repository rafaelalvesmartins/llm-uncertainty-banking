"use client";

import { OPERATORS, useAppContext } from "@/components/AppContextProvider";

// Global context bar — the persistent top selector that makes the dashboard
// "operate like a bank": pick the active client here and every panel that reads
// the context reacts (Atendimento attributes the query to it; Sessões highlights
// it). Model/Environment are honest indicators (one fake backend, one env).
export default function ContextBar() {
  const { client, setClient, customers, operator, setOperator } = useAppContext();
  const active = customers.find((c) => c.customer_id === client);
  const persona = active?.block_summaries?.persona;

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 12,
        padding: "8px 12px",
        margin: "0 0 6px",
        background: "#0b1220",
        border: "1px solid #1e293b",
        borderRadius: 8,
      }}
    >
      <span style={{ fontSize: 10, color: "#94a3b8", textTransform: "uppercase", letterSpacing: 0.5 }}>Context</span>
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#cbd5e1" }}>
        Customer
        <select
          value={client}
          onChange={(e) => setClient(e.target.value)}
          title="Active customer — attributes the query and filters the session view"
          style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, padding: "4px 8px", color: "#e2e8f0", fontSize: 12 }}
        >
          <option value="demo">demo (default)</option>
          {customers
            .filter((c) => c.customer_id !== "demo")
            .map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.customer_id}
              </option>
            ))}
        </select>
      </label>
      {persona && (
        <span
          className="muted"
          title={persona}
          style={{ fontSize: 11, maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {persona}
        </span>
      )}
      <span style={{ marginLeft: "auto", display: "flex", gap: 14, alignItems: "center" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#94a3b8" }}>
          Operator
          <select
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            title="Demo operator — attributes change submission/approval. No real auth (phase v6)."
            style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, padding: "3px 6px", color: "#e2e8f0", fontSize: 11 }}
          >
            {OPERATORS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <span style={{ fontSize: 11, color: "#94a3b8" }}>
          Model: <code style={{ fontSize: 10, color: "#cbd5e1" }}>fake-ai:v1</code>
        </span>
        <span style={{ fontSize: 11, color: "#94a3b8" }}>
          Environment: <strong style={{ color: "#cbd5e1" }}>Demo</strong>
        </span>
      </span>
    </div>
  );
}
