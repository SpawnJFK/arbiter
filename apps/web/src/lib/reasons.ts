// Human labels for the machine reason codes in Segment.reasons (hard QA codes and
// "<dimension>:<severity>" judge findings) and in exception reasons.

const CODES: Record<string, string> = {
  term_forbidden: "Forbidden glossary term used",
  term_missing: "Mandatory glossary term missing",
  term_preferred_missing: "Preferred glossary term not used",
  dnt_changed: "Do-not-translate term was changed",
  term_type: "Glossary term has the wrong form",
  empty_target: "Empty translation",
  untranslated: "Left untranslated",
  length_exceeded: "Longer than the allowed length",
  number_mismatch: "Numbers differ from the source",
  placeholder_mismatch: "Placeholders differ from the source",
  whitespace_mismatch: "Leading or trailing spaces differ",
  tag_missing: "Inline tag missing",
  tag_extra: "Inline tag not in the source",
  tag_malformed: "Malformed inline tag",
  tag_order: "Inline tags in an invalid order",
  tag_pair_dropped: "Formatting pair dropped",
  tag_unbalanced: "Half of a tag pair missing",
  tag_unknown: "Unknown inline tag",
};

export function reasonLabel(raw: string): string {
  const r = raw.trim();
  if (CODES[r]) return CODES[r];
  const m = /^([a-z_]+):(neutral|minor|major|critical)$/.exec(r);
  if (m) return `${cap(m[1].replace(/_/g, " "))} error (${m[2]})`;
  return /^[a-z_]+$/.test(r) ? cap(r.replace(/_/g, " ")) : r;
}

/** Exception reasons may be a comma-joined list of codes. */
export function reasonText(raw: string): string {
  if (/^[a-z_:, ]+$/.test(raw)) return raw.split(",").map(reasonLabel).join(", ");
  return raw;
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Readable messages from Segment.signals.term_violations, when present. */
export function violationMessages(signals: Record<string, unknown> | null | undefined): string[] {
  const v = signals?.term_violations;
  if (!Array.isArray(v)) return [];
  return v
    .map((x) => (x && typeof x === "object" && "message" in x ? String((x as { message: unknown }).message) : ""))
    .filter(Boolean);
}
