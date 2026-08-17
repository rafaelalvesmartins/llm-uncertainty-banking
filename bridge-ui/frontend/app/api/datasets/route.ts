import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/datasets`, { cache: "no-store" });
    if (!r.ok) {
      return NextResponse.json({ error: `Bridge API returned ${r.status}` }, { status: 502 });
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
