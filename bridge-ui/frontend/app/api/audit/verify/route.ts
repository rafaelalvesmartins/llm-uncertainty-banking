import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET(req: NextRequest) {
  try {
    // Forward `source` so the at-rest (source=disk) chain re-validation is reachable
    // — the only check that catches an out-of-band tamper of persisted rows. Without
    // this the "Chain intact" banner is always memory-only and a disk tamper passes.
    const source = req.nextUrl.searchParams.get("source");
    const qs = source ? `?source=${encodeURIComponent(source)}` : "";
    const r = await fetch(`${BRIDGE_API}/audit/verify${qs}`, { cache: "no-store" });
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
