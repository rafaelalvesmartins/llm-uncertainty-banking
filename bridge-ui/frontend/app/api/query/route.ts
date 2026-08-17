import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// B-NEW-20 (round 10): Next.js default cuts route handlers at 30s,
// returning 502 silently when Ollama is slow (avg now 44s for complex
// queries). Pin to Node.js runtime + 90s to match QueryPanel's
// AbortController so the user sees a real response, not an opaque 502.
export const runtime = "nodejs";
export const maxDuration = 90;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const r = await fetch(`${BRIDGE_API}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    // N8-4 (v8 review): preserve upstream 4xx (e.g. 422 schema-validation
    // body, 429 rate-limit) so the client gets the structured Pydantic
    // error instead of an opaque 502. 5xx and 502 stay reserved for true
    // upstream-unreachable failures.
    const data = await r.json().catch(() => ({ error: "upstream non-JSON" }));
    if (r.status >= 400 && r.status < 500) {
      return NextResponse.json(data, { status: r.status });
    }
    if (!r.ok) {
      return NextResponse.json(
        { error: `Bridge API returned ${r.status}`, upstream: data },
        { status: 502 }
      );
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("[query] upstream fetch failed:", err);
    return NextResponse.json(
      { error: "Bridge backend is unreachable." },
      { status: 502 }
    );
  }
}
