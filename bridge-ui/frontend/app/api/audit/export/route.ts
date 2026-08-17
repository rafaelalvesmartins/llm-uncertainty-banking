import { NextRequest, NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET(req: NextRequest) {
  try {
    const search = req.nextUrl.search; // pass ?format=&source= through
    const upstream = await fetch(
      `${BRIDGE_API}/audit/export${search}`,
      { cache: "no-store" },
    );
    if (!upstream.ok) {
      return NextResponse.json(
        { error: `Bridge API returned ${upstream.status}` },
        { status: 502 },
      );
    }
    const headers = new Headers();
    const ct = upstream.headers.get("content-type");
    if (ct) headers.set("content-type", ct);
    const cd = upstream.headers.get("content-disposition");
    if (cd) headers.set("content-disposition", cd);
    return new NextResponse(upstream.body, { status: 200, headers });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 },
    );
  }
}
