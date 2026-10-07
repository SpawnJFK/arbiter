import { NextResponse, type NextRequest } from "next/server";
import { ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/config";

/**
 * GET /logout?next=... clears the session cookies and sends the user to /login.
 * Server components redirect here on a backend 401 (cookies can only be changed in a
 * route handler), which breaks any redirect loop caused by an expired token.
 */
export function GET(req: NextRequest) {
  const next = req.nextUrl.searchParams.get("next");
  const url = new URL("/login", req.url);
  if (next && next.startsWith("/") && !next.startsWith("//")) url.searchParams.set("next", next);
  const res = NextResponse.redirect(url);
  res.cookies.delete(TOKEN_COOKIE);
  res.cookies.delete(ROLE_COOKIE);
  return res;
}
