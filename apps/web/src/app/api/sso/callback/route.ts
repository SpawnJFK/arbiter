import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/config";
import { safeNext } from "@/lib/roles";
import type { User } from "@/lib/types";

const MAX_AGE = 60 * 60 * 12; // same as /api/session; the backend's JWT expiry still wins

/**
 * GET /api/sso/callback?code=&state=  The IdP's redirect URI (register
 * <ARBITER_WEB_BASE_URL>/api/sso/callback at the IdP). The backend validates everything
 * (state, PKCE, id_token); this handler only stores the session the same way /api/session
 * does: token in an httpOnly cookie, never in browser JavaScript.
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const back = (code: string) => {
    const url = new URL("/login", req.url);
    url.searchParams.set("sso_error", code);
    return NextResponse.redirect(url);
  };
  if (sp.get("error")) return back("idp_error");
  const code = sp.get("code");
  const state = sp.get("state");
  if (!code || !state) return back("sso_failed");

  const res = await backendFetch(`/auth/sso/callback?${new URLSearchParams({ code, state })}`, {
    headers: { Accept: "application/json" },
  });
  const data = (await res.json().catch(() => null)) as
    | { token?: string; user?: User; redirect?: string | null; error?: { code?: string } }
    | null;
  if (!res.ok || !data?.token || !data.user) return back(data?.error?.code ?? "sso_failed");

  const jar = await cookies();
  const opts = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production" && req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: MAX_AGE,
  };
  jar.set(TOKEN_COOKIE, data.token, opts);
  jar.set(ROLE_COOKIE, data.user.role, opts);
  return NextResponse.redirect(new URL(safeNext(data.redirect ?? null, data.user.role), req.url));
}
