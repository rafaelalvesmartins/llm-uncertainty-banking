import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// N8-2 (v8 review): /api/docs/corpus was renamed to /api/corpus, breaking
// any external integration on the old path. Add an alias here that proxies
// to the same backend endpoint as /api/corpus so both paths work.
export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/docs/corpus`, { cache: "no-store" });
    const body = await r.json();
    return NextResponse.json(body, { status: r.status });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
