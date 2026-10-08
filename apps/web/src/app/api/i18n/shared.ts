import "server-only";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/config";
import { getI18n } from "@/lib/i18n/server";

/** Admin session for the language routes, or an error response. */
export async function adminToken(): Promise<{ token: string } | { error: NextResponse }> {
  const jar = await cookies();
  const token = jar.get(TOKEN_COOKIE)?.value;
  const { t } = await getI18n();
  if (!token) return { error: apiError(401, "unauthenticated", t("errors.signInFirst")) };
  if (jar.get(ROLE_COOKIE)?.value !== "admin") return { error: apiError(403, "forbidden", t("errors.adminOnly")) };
  return { token };
}

export function apiError(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
  return NextResponse.json({ error: { code, message, details } }, { status });
}

/** Locale codes as the backend normalises them (de, pt-BR, sr-Latn-RS); null when invalid. */
export function normalizeLocale(raw: string | null | undefined): string | null {
  const parts = (raw ?? "").trim().replace(/_/g, "-").split("-").filter(Boolean);
  if (!parts.length || !/^[a-zA-Z]{2,3}$/.test(parts[0]) || parts.some((p) => !/^[a-zA-Z0-9]{1,8}$/.test(p))) return null;
  return parts
    .map((p, i) => (i === 0 ? p.toLowerCase() : p.length === 4 && /^[a-zA-Z]+$/.test(p) ? p[0].toUpperCase() + p.slice(1).toLowerCase() : p.length <= 3 ? p.toUpperCase() : p))
    .join("-");
}
