import type { Translator } from "./i18n/core";

export const LANGS = [
  "en", "en-GB", "de", "fr", "fr-CA", "es", "es-MX", "it", "pt-PT", "pt-BR", "nl", "sv", "da", "nb", "fi",
  "pl", "cs", "sk", "hu", "ro", "bg", "el", "hr", "sr", "sl", "uk", "ru", "tr", "ar", "he",
  "ja", "ko", "zh-CN", "zh-TW", "th", "vi", "id", "hi",
];

/** Content types (backend domains). Labels live in messages/en.json as `contentType.<value>`. */
export const CONTENT_TYPES = ["general", "marketing", "software_ui", "support", "technical", "legal", "financial", "regulatory"].map((value) => ({ value }));

export const DOMAINS = CONTENT_TYPES.map((c) => c.value);

export function contentTypeLabel(t: Translator, v: string | null | undefined): string {
  if (!v) return "–";
  const key = `contentType.${v}`;
  return t.has(key) ? t(key) : v.replace(/_/g, " ");
}
