import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Ollama can take tens of seconds (cold model load). Next's default 30s handler
// cap would 502 silently mid-answer — pin the runtime + 90s to match the client
// AbortController (mirrors app/api/query/route.ts).
export const runtime = "nodejs";
export const maxDuration = 90;

export async function POST(req: Request) {
  try {
    const body = await req.text();
    const r = await fetch(`${BRIDGE_API}/assistant/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    if (!r.ok) {
      return NextResponse.json({ error: `Bridge API returned ${r.status}` }, { status: 502 });
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    console.error("[assistant] upstream fetch failed:", err);
    return NextResponse.json({ error: "Assistant backend is unreachable." }, { status: 502 });
  }
}
