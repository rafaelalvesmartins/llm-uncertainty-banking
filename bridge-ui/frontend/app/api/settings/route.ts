import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Proxy the runtime demo controls (Bloco A2): GET reads current values,
// PUT applies a partial update (guard_threshold / cache_enabled).
export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/settings`, { cache: "no-store" });
    if (!r.ok) {
      return NextResponse.json(
        { error: `Bridge API returned ${r.status}` },
        { status: 502 },
      );
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}

export async function PUT(req: Request) {
  try {
    const body = await req.json();
    const r = await fetch(`${BRIDGE_API}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({ error: "non-JSON response" }));
    return NextResponse.json(data, { status: r.status });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
