import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  try {
    const body = await req.text();
    const r = await fetch(`${BRIDGE_API}/governance/changes/${params.id}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    // Forward the backend's JSON (incl. {detail} on 4xx) so the UI can surface the
    // exact governance reason (replay-guard, SoD-on-apply, config_hash, demo-safe).
    const text = await r.text();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      json = { detail: text };
    }
    return NextResponse.json(json, { status: r.status });
  } catch (err) {
    return NextResponse.json({ detail: (err as Error).message }, { status: 502 });
  }
}
