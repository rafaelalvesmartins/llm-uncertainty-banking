import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// Backward-compat POST alias for the RESTful DELETE /api/audit. Some
// older Next.js builds (cached .next/) call POST /clear. Keeping this
// alias prevents 404s while clients migrate to the canonical verb.
export async function POST() {
  try {
    const r = await fetch(`${BRIDGE_API}/audit`, {
      method: "DELETE",
      cache: "no-store",
    });
    return NextResponse.json(await r.json());
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
