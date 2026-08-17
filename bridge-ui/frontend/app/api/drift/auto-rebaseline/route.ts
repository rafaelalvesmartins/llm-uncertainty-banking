import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const every = req.nextUrl.searchParams.get("every");
    if (every === null) {
      return NextResponse.json(
        { error: "missing required query parameter: every" },
        { status: 422 },
      );
    }
    const operator = req.nextUrl.searchParams.get("operator") ?? "";
    const r = await fetch(
      `${BRIDGE_API}/drift/auto-rebaseline?every=${encodeURIComponent(every)}&operator=${encodeURIComponent(operator)}`,
      { method: "POST", cache: "no-store" },
    );
    const data = await r.json().catch(() => ({ error: "upstream non-JSON" }));
    if (r.status >= 400 && r.status < 500) {
      return NextResponse.json(data, { status: r.status });
    }
    if (!r.ok) {
      return NextResponse.json(
        { error: `Bridge API returned ${r.status}`, upstream: data },
        { status: 502 },
      );
    }
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
