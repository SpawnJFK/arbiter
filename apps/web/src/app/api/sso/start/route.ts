import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { IS_MOCK } from "@/lib/config";

/**
 * GET /api/sso/start?email=&next=  Asks the backend for the IdP authorization URL (it answers
 * 302 with state, nonce and PKCE challenge) and sends the browser there. Errors go back to
 * /login with `sso_error=<code>`.
 */
export async function GET(req: NextRequest) {
  const email = req.nextUrl.searchParams.get("email") ?? "";
  const next = req.nextUrl.searchParams.get("next") ?? "";
  const back = (code: string) => {
    const url = new URL("/login", req.url);
    url.searchParams.set("sso_error", code);
    if (email) url.searchParams.set("email", email);
    if (next) url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  };
  if (IS_MOCK) return back("not_in_demo");
  if (!email.includes("@")) return back("email_required");

  const qs = new URLSearchParams({ email });
  if (next) qs.set("next", next);
  const res = await backendFetch(`/auth/sso/start?${qs}`, { headers: { Accept: "application/json" } });
  const location = res.headers.get("location");
  if (res.status >= 300 && res.status < 400 && location) return NextResponse.redirect(location);
  const body = (await res.json().catch(() => null)) as { error?: { code?: string } } | null;
  return back(body?.error?.code ?? "sso_failed");
}
