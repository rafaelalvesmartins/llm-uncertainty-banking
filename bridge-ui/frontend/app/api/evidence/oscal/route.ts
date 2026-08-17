import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Proxy the backend's OSCAL 1.1.2 component-definition through unchanged (it is
// already a JSON document, so pass the raw text — don't re-wrap it). A 404 from
// the backend (no real benchmark run yet) is forwarded with its detail.
export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/evidence/oscal`, { cache: "no-store" });
    const body = await r.text();
    if (!r.ok) {
      return NextResponse.json(
        { error: `Bridge API returned ${r.status}`, detail: body },
        { status: r.status },
      );
    }
    return new Response(body, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("[evidence/oscal] upstream fetch failed:", err);
    return NextResponse.json({ error: "Bridge backend is unreachable." }, { status: 502 });
  }
}
