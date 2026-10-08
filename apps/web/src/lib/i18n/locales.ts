import { SOURCE_LOCALE } from "./core";

export interface LocaleInfo {
  locale: string;
  name: string;
  enabled: boolean;
  message_count: number | null;
  updated_at: string | null;
}

/** Pick the best enabled locale for an Accept-Language header (exact match, then primary subtag). */
export function negotiate(acceptLanguage: string | null | undefined, enabled: string[]): string {
  if (!acceptLanguage) return SOURCE_LOCALE;
  const wanted = acceptLanguage
    .split(",")
    .map((part) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
      return { tag: tag.trim(), q: q ? Number(q.slice(2)) || 0 : 1 };
    })
    .filter((x) => x.tag && x.tag !== "*" && x.q > 0)
    .sort((a, b) => b.q - a.q);
  const lower = enabled.map((l) => l.toLowerCase());
  for (const { tag } of wanted) {
    const i = lower.indexOf(tag.toLowerCase());
    if (i >= 0) return enabled[i];
    const primary = tag.split("-")[0].toLowerCase();
    const j = lower.findIndex((l) => l === primary || l.split("-")[0] === primary);
    if (j >= 0) return enabled[j];
  }
  return SOURCE_LOCALE;
}

export function resolveLocale(cookie: string | null | undefined, acceptLanguage: string | null | undefined, enabled: string[]): string {
  if (cookie && enabled.includes(cookie)) return cookie;
  return negotiate(acceptLanguage, enabled);
}
