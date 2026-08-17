import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Proxy the backend's FastAPI schema so the Feature Map (Bloco A5) can
// cross-check every declared endpoint against what the server actually
// exposes — surfacing drift instead of letting the map silently rot.
export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/openapi.json`, { cache: "no-store" });
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
