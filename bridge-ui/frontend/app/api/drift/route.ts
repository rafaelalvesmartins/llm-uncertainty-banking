import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/drift`, { cache: "no-store" });
    const data = await r.json().catch(() => ({ error: "upstream non-JSON" }));
    if (!r.ok) return NextResponse.json(data, { status: r.status });
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    // Forward the acting operator so the rebaseline is attributed on the audit chain.
    const operator = req.nextUrl.searchParams.get("operator") ?? "";
    const r = await fetch(`${BRIDGE_API}/drift/baseline?operator=${encodeURIComponent(operator)}`, {
      method: "POST",
      cache: "no-store",
    });
    const data = await r.json().catch(() => ({ error: "upstream non-JSON" }));
    if (!r.ok) return NextResponse.json(data, { status: r.status });
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
