export const LANGS = [
  "en", "en-GB", "de", "fr", "fr-CA", "es", "es-MX", "it", "pt-PT", "pt-BR", "nl", "sv", "da", "nb", "fi",
  "pl", "cs", "sk", "hu", "ro", "bg", "el", "hr", "sr", "sl", "uk", "ru", "tr", "ar", "he",
  "ja", "ko", "zh-CN", "zh-TW", "th", "vi", "id", "hi",
];

export const CONTENT_TYPES = [
  { value: "general", label: "General" },
  { value: "marketing", label: "Marketing" },
  { value: "software_ui", label: "Software UI" },
  { value: "support", label: "Support content" },
  { value: "technical", label: "Technical documentation" },
  { value: "legal", label: "Legal" },
  { value: "financial", label: "Financial" },
  { value: "regulatory", label: "Regulatory / life sciences" },
];

export const DOMAINS = CONTENT_TYPES.map((c) => c.value);

export function contentTypeLabel(v: string | null | undefined): string {
  return CONTENT_TYPES.find((c) => c.value === v)?.label ?? (v ? v.replace(/_/g, " ") : "–");
}
