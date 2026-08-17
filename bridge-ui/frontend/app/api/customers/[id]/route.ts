import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    const r = await fetch(
      `${BRIDGE_API}/customers/${encodeURIComponent(params.id)}`,
      { cache: "no-store" },
    );
    // Preserve upstream 404 (resource genuinely missing) instead of masking
    // it as 502 (upstream-bridge-unreachable). 5xx is reserved for real
    // proxy/upstream failures so the client can distinguish "doesn't exist"
    // from "BFF can't reach Bridge."
    if (r.status === 404) {
      const body = await r.json().catch(() => ({ error: "not found" }));
      return NextResponse.json(body, { status: 404 });
    }
    if (!r.ok) {
      return NextResponse.json(
        { error: `Bridge API returned ${r.status}` },
        { status: 502 },
      );
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
