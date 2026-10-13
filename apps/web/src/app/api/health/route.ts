import { NextResponse } from "next/server";

/** GET /api/health: kamal-proxy and the load balancer probe this; no backend call, no session. */
export function GET() {
  return NextResponse.json(
    { ok: true, commit: process.env.ARBITER_GIT_SHA ?? "unknown" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
