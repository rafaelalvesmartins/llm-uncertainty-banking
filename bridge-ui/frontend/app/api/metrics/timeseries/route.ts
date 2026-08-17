import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Thin proxy for the backend cumulative-decision time series (dashboard trend chart).
export async function GET(req: NextRequest) {
  try {
    const qs = req.nextUrl.searchParams.toString();
    const r = await fetch(`${BRIDGE_API}/metrics/timeseries${qs ? `?${qs}` : ""}`, { cache: "no-store" });
    const body = await r.json();
    return NextResponse.json(body, { status: r.status });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
