import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET() {
  try {
    const r = await fetch(`${BRIDGE_API}/governance/changes`, { cache: "no-store" });
    // Forward the upstream body + original status (e.g. FastAPI {detail}) so the client
    // surfaces the real reason instead of a generic 502 — mirrors the POST half below.
    const text = await r.text();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      json = { error: text || `Bridge API returned ${r.status}` };
    }
    return NextResponse.json(json, { status: r.status });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.text();
    const r = await fetch(`${BRIDGE_API}/governance/changes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    if (!r.ok) {
      // Forward the upstream JSON body verbatim (e.g. FastAPI {detail: "…"}) so the
      // client's apiErrorText() extracts a clean message instead of a raw blob.
      const text = await r.text();
      let json: unknown;
      try {
        json = JSON.parse(text);
      } catch {
        json = { error: text || `Bridge API returned ${r.status}` };
      }
      return NextResponse.json(json, { status: r.status });
    }
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 502 });
  }
}
