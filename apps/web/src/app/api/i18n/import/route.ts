import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { SOURCE_LOCALE, type Messages } from "@/lib/i18n/core";
import { getI18n, invalidateI18nCache, SOURCE_MESSAGES } from "@/lib/i18n/server";
import { ImportError, parseImport } from "@/lib/i18n/transfer";
import { adminToken, apiError, normalizeLocale } from "../shared";

const MAX_BYTES = 5 * 1024 * 1024;

/**
 * POST /api/i18n/import  multipart: file, locale, mode=merge|replace  (admin)
 * Parses JSON / CSV / XLIFF here, then PUTs /admin/i18n/messages/{locale} with the English
 * source so the backend can reject translations whose {placeholders} differ.
 */
export async function POST(req: NextRequest) {
  const auth = await adminToken();
  if ("error" in auth) return auth.error;
  const { t } = await getI18n();
  const form = await req.formData().catch(() => null);
  const file = form?.get("file");
  const locale = normalizeLocale(String(form?.get("locale") ?? ""));
  const mode = form?.get("mode") === "replace" ? "replace" : "merge";
  if (!locale) return apiError(422, "validation_error", t("errors.invalidLocale"));
  if (locale === SOURCE_LOCALE) return apiError(422, "validation_error", t("errors.sourceReadOnly"));
  if (!(file instanceof File) || file.size === 0) return apiError(422, "validation_error", t("errors.fileRequired"));
  if (file.size > MAX_BYTES) return apiError(413, "too_large", t("errors.fileTooLarge"));

  let parsed;
  try {
    parsed = parseImport(await file.text(), file.name, SOURCE_MESSAGES);
  } catch (e) {
    return apiError(422, "unreadable_file", e instanceof ImportError ? t("errors.unreadableFileDetail", { detail: e.message }) : t("errors.unreadableFile"));
  }
  const keys = Object.keys(parsed.messages);
  if (keys.length === 0 && mode === "merge") {
    return apiError(422, "nothing_to_import", t("errors.nothingToImport"), { unknown: parsed.unknown.slice(0, 50), empty: parsed.empty });
  }
  const source: Messages = Object.fromEntries(keys.map((k) => [k, SOURCE_MESSAGES[k]]));
  const res = await backendFetch(`/admin/i18n/messages/${encodeURIComponent(locale)}`, {
    method: "PUT",
    token: auth.token,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ messages: parsed.messages, mode, source }),
  });
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!res.ok) return NextResponse.json(data ?? { error: { code: `http_${res.status}`, message: res.statusText, details: {} } }, { status: res.status });
  invalidateI18nCache(locale);
  return NextResponse.json({ ...data, format: parsed.format, unknown: parsed.unknown.slice(0, 50), unknown_count: parsed.unknown.length, empty: parsed.empty });
}
