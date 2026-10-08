// Human labels for the machine reason codes in Segment.reasons (hard QA codes and
// "<dimension>:<severity>" judge findings) and in exception reasons. Labels: `reason.<code>` keys.
import type { Translator } from "./i18n/core";

export function reasonLabel(t: Translator, raw: string): string {
  const r = raw.trim();
  if (t.has(`reason.${r}`)) return t(`reason.${r}`);
  const m = /^([a-z_]+):(neutral|minor|major|critical)$/.exec(r);
  if (m) return t("reason.judgeFinding", { dimension: t.enumLabel(m[1]), severity: t.enumLabel(m[2]) });
  return /^[a-z_]+$/.test(r) ? t.enumLabel(r) : r;
}

/** Exception reasons may be a comma-joined list of codes. */
export function reasonText(t: Translator, raw: string): string {
  if (/^[a-z_:, ]+$/.test(raw)) return raw.split(",").map((x) => reasonLabel(t, x)).join(", ");
  return raw;
}

/** Readable messages from Segment.signals.term_violations, when present. */
export function violationMessages(signals: Record<string, unknown> | null | undefined): string[] {
  const v = signals?.term_violations;
  if (!Array.isArray(v)) return [];
  return v
    .map((x) => (x && typeof x === "object" && "message" in x ? String((x as { message: unknown }).message) : ""))
    .filter(Boolean);
}
