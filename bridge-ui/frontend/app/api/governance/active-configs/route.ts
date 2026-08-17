import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET(req: Request) {
  try {
    const domain = new URL(req.url).searchParams.get("domain");
    const qs = domain ? `?domain=${encodeURIComponent(domain)}` : "";
    const r = await fetch(`${BRIDGE_API}/governance/active-configs${qs}`, { cache: "no-store" });
    // Forward the upstream body + original status so any backend detail propagates,
    // consistent with the other governance proxy routes.
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
