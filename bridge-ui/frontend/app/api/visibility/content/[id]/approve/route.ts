import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Human approval of a content draft. Only PASSTHROUGH drafts succeed; the
// backend refuses (409) FLAG/ESCALATE. No external publication occurs.
export async function POST(
  _req: Request,
  { params }: { params: { id: string } },
) {
  try {
    const r = await fetch(
      `${BRIDGE_API}/visibility/content/${encodeURIComponent(params.id)}/approve`,
      { method: "POST" },
    );
    const data = await r.json().catch(() => ({ error: "non-JSON response" }));
    return NextResponse.json(data, { status: r.status });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
