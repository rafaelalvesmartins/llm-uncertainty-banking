import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// POST /visibility/schedule — enable/disable the runtime collection scheduler.
// Body: { every_minutes: number } (0 = off). No restart needed.
export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const r = await fetch(`${BRIDGE_API}/visibility/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({ error: "non-JSON response" }));
    return NextResponse.json(data, { status: r.status });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
