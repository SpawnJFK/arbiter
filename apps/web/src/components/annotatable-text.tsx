"use client";

import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import { cn } from "@/lib/cn";
import { TOKEN_RE, tagLabel } from "@/lib/tags";
import type { Span } from "@/lib/types";

type Seg = { kind: "text"; start: number; raw: string; display: string } | { kind: "tag"; start: number; raw: string };

function segments(s: string): Seg[] {
  const out: Seg[] = [];
  let last = 0;
  let textStart = 0;
  let raw = "";
  let display = "";
  const flush = () => {
    if (raw) out.push({ kind: "text", start: textStart, raw, display });
    raw = "";
    display = "";
  };
  for (const m of s.matchAll(TOKEN_RE)) {
    const idx = m.index ?? 0;
    if (!raw) textStart = last;
    raw += s.slice(last, idx);
    display += s.slice(last, idx);
    if (m[0] === "⟦⟦" || m[0] === "⟧⟧") {
      if (!raw) textStart = idx;
      raw += m[0];
      display += m[0][0];
    } else {
      flush();
      out.push({ kind: "tag", start: idx, raw: m[0] });
    }
    last = idx + m[0].length;
  }
  if (!raw) textStart = last;
  raw += s.slice(last);
  display += s.slice(last);
  flush();
  return out;
}

/** Map a character offset in the displayed text of a piece to an offset in the raw tagged string. */
function rawOffset(seg: Extract<Seg, { kind: "text" }>, displayOffset: number): number {
  let r = 0;
  for (let i = 0; i < displayOffset && i < seg.display.length; i++) {
    const ch = seg.display[i];
    r += ch === "⟦" || ch === "⟧" ? 2 : 1;
  }
  return seg.start + r;
}

export interface AnnotatableHandle {
  /** Current selection inside this text as [start, end) offsets into the tagged string. */
  selectionSpan: () => Span | null;
}

/**
 * Read-only tagged text whose selection can be turned into offsets in the original tagged
 * string. Used to annotate errors on the machine translation being evaluated.
 */
export const AnnotatableText = forwardRef<AnnotatableHandle, { value: string; className?: string; label?: string }>(
  function AnnotatableText({ value, className, label }, ref) {
    const root = useRef<HTMLDivElement>(null);
    const segs = useMemo(() => segments(value), [value]);

    useImperativeHandle(ref, () => ({
      selectionSpan: () => {
        const el = root.current;
        const sel = window.getSelection();
        if (!el || !sel || sel.rangeCount === 0) return null;
        const r = sel.getRangeAt(0);
        if (!el.contains(r.startContainer) || !el.contains(r.endContainer)) return null;
        const pos = (node: Node, offset: number, isEnd: boolean): number => {
          const host = (node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as Element))?.closest<HTMLElement>("[data-i]");
          if (!host) {
            // Selection boundary on the root element: offset counts child pieces.
            const child = el.children[Math.min(offset, el.children.length - 1)] as HTMLElement | undefined;
            const s = child ? segs[Number(child.dataset.i)] : undefined;
            if (!s) return value.length;
            return offset >= el.children.length ? value.length : s.start;
          }
          const s = segs[Number(host.dataset.i)];
          if (s.kind === "tag") return isEnd ? s.start + s.raw.length : s.start;
          return node.nodeType === Node.TEXT_NODE ? rawOffset(s, offset) : isEnd ? s.start + s.raw.length : s.start;
        };
        const a = pos(r.startContainer, r.startOffset, false);
        const b = pos(r.endContainer, r.endOffset, true);
        return a <= b ? [a, b] : [b, a];
      },
    }));

    return (
      <div ref={root} aria-label={label} className={cn("whitespace-pre-wrap break-words select-text", className)}>
        {segs.map((s, i) =>
          s.kind === "tag" ? (
            <span key={i} data-i={i} className="tag-chip">
              {tagLabel(s.raw)}
            </span>
          ) : (
            <span key={i} data-i={i}>
              {s.display}
            </span>
          ),
        )}
      </div>
    );
  },
);
