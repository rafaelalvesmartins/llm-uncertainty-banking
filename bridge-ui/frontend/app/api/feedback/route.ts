import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/feedback`, { cache: "no-store" });
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

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const r = await fetch(`${BRIDGE_API}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
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
