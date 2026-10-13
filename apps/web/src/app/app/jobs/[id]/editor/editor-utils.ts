import { TOKEN_RE } from "@/lib/tags";

/** Raw offsets in a tagged string where a segment may be split: right after whitespace, outside
 * any open formatting pair and never inside a tag or an escape. Mirrors tms/tagged.py. */
export function cutPoints(tagged: string): number[] {
  const out: number[] = [];
  const stack: string[] = [];
  let last = 0;
  const scanText = (from: number, to: number) => {
    if (stack.length > 0) return;
    for (let i = from; i < to; i++) {
      const next = tagged[i + 1];
      if (/\s/.test(tagged[i]) && next !== undefined && !/\s/.test(next)) out.push(i + 1);
    }
  };
  for (const m of tagged.matchAll(TOKEN_RE)) {
    const idx = m.index ?? 0;
    scanText(last, idx);
    const tok = m[0];
    if (tok !== "⟦⟦" && tok !== "⟧⟧") {
      const inner = tok.slice(1, -1);
      if (inner.startsWith("/")) stack.pop();
      else if (!inner.endsWith("/")) stack.push(inner);
    }
    last = idx + tok.length;
  }
  scanText(last, tagged.length);
  return out.filter((o) => o > 0 && o < tagged.length);
}

/** Split a tagged string into display chunks between the given cut points. */
export function chunksAt(tagged: string, cuts: number[]): { text: string; end: number }[] {
  const out: { text: string; end: number }[] = [];
  let from = 0;
  for (const c of cuts) {
    out.push({ text: tagged.slice(from, c), end: c });
    from = c;
  }
  out.push({ text: tagged.slice(from), end: tagged.length });
  return out;
}

export const ROW_HEIGHT = 76;
export const DONE_STATES = ["auto_approved", "reviewed", "delivered"];
export const EDITABLE_STATES = ["needs_review", "auto_approved", "reviewed", "delivered"];
