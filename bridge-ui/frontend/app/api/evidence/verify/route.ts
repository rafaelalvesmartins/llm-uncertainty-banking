import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function POST(req: Request) {
  try {
    const body = await req.text();
    const r = await fetch(`${BRIDGE_API}/evidence/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    if (!r.ok) {
      return NextResponse.json({ error: `Bridge API returned ${r.status}` }, { status: 502 });
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
