import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// POST /visibility/run — trigger one collection pass over all monitoring
// prompts. Read-only with respect to the outside world (no publishing).
export async function POST() {
  try {
    const r = await fetch(`${BRIDGE_API}/visibility/run`, { method: "POST" });
    const data = await r.json().catch(() => ({ error: "non-JSON response" }));
    return NextResponse.json(data, { status: r.status });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
