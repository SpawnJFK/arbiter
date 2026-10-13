import { NextResponse, type NextRequest } from "next/server";
import { backendFetch, UNREACHABLE_HEADER } from "@/lib/backend";
import { getI18n } from "@/lib/i18n/server";
import { IS_MOCK } from "@/lib/config";

/**
 * POST /api/password/forgot { email } -> backend POST /v1/auth/password/forgot.
 * Public (no session). The backend answers 202 whether or not the address has an account,
 * and so does this route, so the page never reveals which addresses exist.
 */
export async function POST(req: NextRequest) {
  let email = "";
  try {
    const body = (await req.json()) as { email?: unknown };
    email = typeof body.email === "string" ? body.email.trim() : "";
  } catch {
    email = "";
  }
  if (!email || email.length > 320) {
    const { t } = await getI18n();
    return NextResponse.json({ error: { code: "validation_error", message: t("errors.emailRequired"), details: {} } }, { status: 422 });
  }
  if (IS_MOCK) return NextResponse.json({ ok: true }, { status: 202 });
  const res = await backendFetch("/auth/password/forgot", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email }),
  });
  if (res.headers.get(UNREACHABLE_HEADER)) {
    const { t } = await getI18n();
    return NextResponse.json({ error: { code: "backend_unreachable", message: t("errors.backendUnreachable"), details: {} } }, { status: 502 });
  }
  if (res.status === 202 || res.ok) return NextResponse.json({ ok: true }, { status: 202 });
  const data = await res.json().catch(() => null);
  return NextResponse.json(data ?? { error: { code: `http_${res.status}`, message: res.statusText, details: {} } }, { status: res.status });
}
