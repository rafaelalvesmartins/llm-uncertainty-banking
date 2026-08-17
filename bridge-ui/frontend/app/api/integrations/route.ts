import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET(req: Request) {
  const refresh = new URL(req.url).searchParams.get("refresh");
  const qs = refresh ? "?refresh=1" : "";
  try {
    const r = await fetch(`${BRIDGE_API}/integrations${qs}`, { cache: "no-store" });
    if (!r.ok) {
      return NextResponse.json({ error: `Bridge API returned ${r.status}` }, { status: 502 });
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
