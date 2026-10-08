import { type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { SOURCE_LOCALE, type Messages } from "@/lib/i18n/core";
import { getI18n, SOURCE_MESSAGES } from "@/lib/i18n/server";
import { EXPORT_FORMATS, exportCatalog, type ExportFormat } from "@/lib/i18n/transfer";
import { adminToken, apiError, normalizeLocale } from "../shared";

/** GET /api/i18n/export?locale=de&format=json|csv|xliff  (admin) */
export async function GET(req: NextRequest) {
  const auth = await adminToken();
  if ("error" in auth) return auth.error;
  const { t } = await getI18n();
  const locale = normalizeLocale(req.nextUrl.searchParams.get("locale"));
  const format = (req.nextUrl.searchParams.get("format") ?? "xliff") as ExportFormat;
  if (!locale) return apiError(422, "validation_error", t("errors.invalidLocale"));
  if (!EXPORT_FORMATS.includes(format)) return apiError(422, "validation_error", t("errors.invalidFormat"));

  let targets: Messages = {};
  if (locale !== SOURCE_LOCALE) {
    const res = await backendFetch(`/i18n/messages/${encodeURIComponent(locale)}`, { token: auth.token, headers: { Accept: "application/json" } });
    if (!res.ok) return new Response(res.body, { status: res.status, headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" } });
    targets = ((await res.json()) as { messages?: Messages }).messages ?? {};
  }
  const out = exportCatalog(format, locale, SOURCE_MESSAGES, targets, locale === SOURCE_LOCALE);
  return new Response(out.body, {
    headers: { "Content-Type": out.contentType, "Content-Disposition": `attachment; filename="${out.filename}"`, "Cache-Control": "no-store" },
  });
}
