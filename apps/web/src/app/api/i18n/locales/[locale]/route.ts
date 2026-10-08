import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { getI18n, invalidateI18nCache } from "@/lib/i18n/server";
import { adminToken, apiError, normalizeLocale } from "../../shared";

type Ctx = { params: Promise<{ locale: string }> };

async function forward(method: "PUT" | "DELETE", req: NextRequest, ctx: Ctx) {
  const auth = await adminToken();
  if ("error" in auth) return auth.error;
  const { t } = await getI18n();
  const locale = normalizeLocale((await ctx.params).locale);
  if (!locale) return apiError(422, "validation_error", t("errors.invalidLocale"));
  const body = method === "PUT" ? await req.text() : null;
  const res = await backendFetch(`/admin/i18n/locales/${encodeURIComponent(locale)}`, {
    method,
    token: auth.token,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body,
  });
  // Enabling, renaming or deleting changes what the switcher and every page see: drop the cache.
  if (res.ok) invalidateI18nCache(locale);
  if (res.status === 204) return new NextResponse(null, { status: 204 });
  const data = await res.json().catch(() => null);
  return NextResponse.json(data ?? { error: { code: `http_${res.status}`, message: res.statusText, details: {} } }, { status: res.status });
}

/** PUT /api/i18n/locales/{locale} {name, enabled?} and DELETE: admin locale management with cache invalidation. */
export const PUT = (req: NextRequest, ctx: Ctx) => forward("PUT", req, ctx);
export const DELETE = (req: NextRequest, ctx: Ctx) => forward("DELETE", req, ctx);
