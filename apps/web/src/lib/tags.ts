// Tagged-text model shared with the backend (see CLAUDE.md "Tagged text model"):
//   ⟦1⟧...⟦/1⟧ paired inline tags, ⟦2/⟧ standalone tags, literal brackets escaped as ⟦⟦ and ⟧⟧.

export const TOKEN_RE = /⟦⟦|⟧⟧|⟦\/?\d+\/?⟧/g;

export type Piece = { type: "text"; value: string } | { type: "tag"; value: string };

/** Split tagged text into text pieces (with escapes resolved) and tag tokens. */
export function tokenize(input: string | null | undefined): Piece[] {
  const s = input ?? "";
  const out: Piece[] = [];
  let last = 0;
  let buf = "";
  for (const m of s.matchAll(TOKEN_RE)) {
    const idx = m.index ?? 0;
    buf += s.slice(last, idx);
    if (m[0] === "⟦⟦") buf += "⟦";
    else if (m[0] === "⟧⟧") buf += "⟧";
    else {
      if (buf) out.push({ type: "text", value: buf });
      buf = "";
      out.push({ type: "tag", value: m[0] });
    }
    last = idx + m[0].length;
  }
  buf += s.slice(last);
  if (buf) out.push({ type: "text", value: buf });
  return out;
}

/** Escape literal brackets in a plain text run. */
export function escapeText(s: string): string {
  return s.replace(/⟦/g, "⟦⟦").replace(/⟧/g, "⟧⟧");
}

export function tagsOf(s: string): string[] {
  return tokenize(s)
    .filter((p) => p.type === "tag")
    .map((p) => p.value);
}

function counts(tags: string[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const tag of tags) m.set(tag, (m.get(tag) ?? 0) + 1);
  return m;
}

/** Tags the target is missing vs. the source, and tags it has that the source does not. */
export function diffTags(required: string[], current: string[]): { missing: string[]; extra: string[] } {
  const r = counts(required);
  const c = counts(current);
  const missing: string[] = [];
  const extra: string[] = [];
  for (const [t, n] of r) for (let i = (c.get(t) ?? 0); i < n; i++) missing.push(t);
  for (const [t, n] of c) for (let i = (r.get(t) ?? 0); i < n; i++) extra.push(t);
  return { missing, extra };
}

export function sameTags(a: string, b: string): boolean {
  const d = diffTags(tagsOf(a), tagsOf(b));
  return d.missing.length === 0 && d.extra.length === 0;
}

/** Human label for a chip: ⟦1⟧ -> <1>, ⟦/1⟧ -> </1>, ⟦2/⟧ -> <2/>. */
export function tagLabel(token: string): string {
  return `<${token.slice(1, -1)}>`;
}

/** Plain text (tags removed, escapes resolved), e.g. for spans and search. */
export function plain(s: string): string {
  return tokenize(s)
    .filter((p) => p.type === "text")
    .map((p) => p.value)
    .join("");
}
