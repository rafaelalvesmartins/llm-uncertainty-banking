import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET(req: NextRequest) {
  // The bounded context selects which calibration target the verdict is judged
  // against, so it has to travel through the proxy rather than be pinned here.
  const context = req.nextUrl.searchParams.get("context");
  const qs = context ? `?context=${encodeURIComponent(context)}` : "";
  try {
    const r = await fetch(`${BRIDGE_API}/challenge/nightly${qs}`, {
      cache: "no-store",
    });
    if (!r.ok) {
      // 400 carries an actionable detail (e.g. unknown context) — pass the
      // status through instead of flattening every failure into 502.
      return NextResponse.json(await r.json().catch(() => ({ error: `Bridge API returned ${r.status}` })), {
        status: r.status,
      });
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
