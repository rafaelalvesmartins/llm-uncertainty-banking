import { NextResponse } from "next/server";

const BRIDGE_API = process.env.BRIDGE_API_URL || "http://localhost:8000";

export async function GET() {
  try {
    const [metricsR, healthR, auditR] = await Promise.all([
      fetch(`${BRIDGE_API}/metrics`, { cache: "no-store" }),
      fetch(`${BRIDGE_API}/health`, { cache: "no-store" }),
      fetch(`${BRIDGE_API}/audit?limit=10`, { cache: "no-store" }),
    ]);
    const metrics = await metricsR.json();
    const health = await healthR.json();
    const audit = await auditR.json();
    return NextResponse.json({ metrics, health, audit });
  } catch (err) {
    return NextResponse.json(
      { error: (err as Error).message },
      { status: 502 }
    );
  }
}
