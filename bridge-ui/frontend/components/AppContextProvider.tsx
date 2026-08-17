"use client";

import { createContext, useContext, useEffect, useState } from "react";

// Global operating context — the architectural backbone for "operate like a
// bank": one shared selection (the active client) that drives the panels,
// instead of each panel owning its own local state. Today it carries the
// client; environment/model are honest indicators (one fake backend).
export interface CustomerSummary {
  customer_id: string;
  block_summaries?: Record<string, string>;
}

// Demo operators (NOT authenticated identities — the v6 auth phase replaces
// this). Used by the governed-change workflow to attribute submit/approve.
export const OPERATORS = ["ana.analista", "bruno.validador", "carla.mrm"];

interface AppCtx {
  client: string;
  setClient: (c: string) => void;
  customers: CustomerSummary[];
  operator: string;
  setOperator: (o: string) => void;
}

const Ctx = createContext<AppCtx>({
  client: "demo",
  setClient: () => {},
  customers: [],
  operator: OPERATORS[0],
  setOperator: () => {},
});

export const useAppContext = (): AppCtx => useContext(Ctx);

export default function AppContextProvider({ children }: { children: React.ReactNode }) {
  const [client, setClient] = useState("demo");
  const [operator, setOperator] = useState(OPERATORS[0]);
  const [customers, setCustomers] = useState<CustomerSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/customers", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { customers: [] }))
      .then((j) => {
        if (!cancelled) setCustomers(j.customers || []);
      })
      .catch(() => {
        /* swallow — selector just shows the default */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Ctx.Provider value={{ client, setClient, customers, operator, setOperator }}>{children}</Ctx.Provider>
  );
}
