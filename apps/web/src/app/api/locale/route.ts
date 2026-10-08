import { NextResponse, type NextRequest } from "next/server";
import { LOCALE_COOKIE } from "@/lib/i18n/core";
import { enabledLocales } from "@/lib/i18n/server";

/** POST /api/locale { locale } -> sets the interface language cookie (only enabled locales). */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { locale?: unknown } | null;
  const wanted = typeof body?.locale === "string" ? body.locale : "";
  const locales = await enabledLocales();
  const match = locales.find((l) => l.locale.toLowerCase() === wanted.toLowerCase());
  if (!match) {
    return NextResponse.json({ error: { code: "unknown_locale", message: `Locale "${wanted}" is not enabled.`, details: {} } }, { status: 422 });
  }
  const res = NextResponse.json({ locale: match.locale });
  res.cookies.set(LOCALE_COOKIE, match.locale, { path: "/", sameSite: "lax", maxAge: 60 * 60 * 24 * 365, secure: req.nextUrl.protocol === "https:" });
  return res;
}
