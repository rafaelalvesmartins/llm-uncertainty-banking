import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

// N8-1 (v8 review): /api/audit GET was returning 405 because only DELETE
// was exposed at the BFF. The backend has /audit GET with pagination —
// just needs a thin proxy. Preserves limit + offset query params.
export async function GET(req: NextRequest) {
  try {
    const sp = req.nextUrl.searchParams;
    const qs = sp.toString();
    const url = `${BRIDGE_API}/audit${qs ? `?${qs}` : ""}`;
    const r = await fetch(url, { cache: "no-store" });
    const body = await r.json();
    // N8-4 — preserve upstream status (404 / 422) instead of wrapping as 502.
    return NextResponse.json(body, { status: r.status });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}

export async function DELETE(req: NextRequest) {
  try {
    // Forward the acting operator so the (ungoverned) window rotation is attributed.
    const operator = req.nextUrl.searchParams.get("operator") ?? "";
    const r = await fetch(`${BRIDGE_API}/audit?operator=${encodeURIComponent(operator)}`, {
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
