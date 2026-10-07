import { NextResponse, type NextRequest } from "next/server";
import { ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/config";
import { AREA_ROLES, areaFor, homeForRole } from "@/lib/roles";
import type { Role } from "@/lib/types";

/**
 * Route guard (Next 16 `proxy.ts`, formerly middleware). It only routes: the backend is the
 * authority and still rejects a bad token with 401, which sends the user through /logout.
 *  - no session on /app, /reviewer, /admin  -> /login?next=<path>
 *  - signed in but wrong area for the role  -> that role's home
 */
export function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const area = areaFor(pathname);
  if (!area) return NextResponse.next();

  const token = req.cookies.get(TOKEN_COOKIE)?.value;
  const role = req.cookies.get(ROLE_COOKIE)?.value;
  if (!token || !role) {
    const url = new URL("/login", req.url);
    url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  if (!AREA_ROLES[area].includes(role as Role)) {
    return NextResponse.redirect(new URL(homeForRole(role), req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/app", "/app/:path*", "/reviewer", "/reviewer/:path*", "/admin", "/admin/:path*"],
};
