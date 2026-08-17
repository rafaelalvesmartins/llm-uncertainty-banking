import { NextRequest } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Pin to Node runtime + long maxDuration so SSE stays open through a
// 45s Ollama call. Default Next.js 30s would cut the stream off mid-flight.
export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  const body = await req.text();
  let upstream: Response;
  try {
    upstream = await fetch(`${BRIDGE_API}/query/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      // @ts-expect-error duplex required for streaming POST in Node fetch
      duplex: "half",
    });
  } catch (e) {
    // Backend unreachable (ECONNREFUSED / DNS / timeout). Without this the
    // handler throws and Next returns an opaque HTML 500 that the SSE reader
    // cannot parse — the client showed "Stream ended without a done event".
    console.error("[query/stream] upstream fetch failed:", e);
    return new Response(
      JSON.stringify({ status_code: 502, detail: "Bridge backend is unreachable." }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  // Pass the stream through as-is — Response.body is a ReadableStream that
  // the browser EventSource alternative (fetch + reader) can consume.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
