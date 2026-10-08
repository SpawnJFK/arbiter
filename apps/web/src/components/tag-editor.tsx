"use client";

import { useI18n } from "@/lib/i18n/client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { diffTags, escapeText, tagLabel, tagsOf, tokenize } from "@/lib/tags";
import type { Span } from "@/lib/types";

export interface TagEditorHandle {
  focus: () => void;
  /** Current selection as [start, end) offsets in the serialized tagged string. */
  selectionSpan: () => Span | null;
  insertTag: (token: string) => void;
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** Tags the target must contain (from the source). */
  requiredTags: string[];
  id?: string;
  ariaLabel?: string;
  ariaDescribedBy?: string;
  className?: string;
  autoFocus?: boolean;
  placeholder?: string;
  dir?: "ltr" | "rtl" | "auto";
  onKeyDown?: (e: React.KeyboardEvent<HTMLDivElement>) => void;
}

function serializeNodes(nodes: Iterable<Node>): string {
  let out = "";
  for (const n of nodes) {
    if (n.nodeType === Node.TEXT_NODE) out += escapeText((n.textContent ?? "").replace(/ /g, " "));
    else if (n instanceof HTMLElement) {
      if (n.dataset.tag) out += n.dataset.tag;
      else if (n.tagName === "BR") continue;
      else out += serializeNodes(n.childNodes);
    }
  }
  return out;
}

function chipFor(token: string, extra: boolean): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = "tag-chip";
  span.contentEditable = "false";
  span.dataset.tag = token;
  span.dataset.extra = String(extra);
  span.textContent = tagLabel(token);
  span.setAttribute("aria-label", `tag ${tagLabel(token)}`);
  return span;
}

/**
 * Tag-aware inline editor. Inline tags render as atomic, non-editable chips. Deleting or
 * overwriting a required chip is blocked at `beforeinput`; if a browser path slips through,
 * the previous valid content is restored. Extra tags (not in the source) are shown in red and
 * may be deleted. Pasted content is inserted as plain text, so brackets become literals.
 */
export const TagEditor = forwardRef<TagEditorHandle, Props>(function TagEditor(
  { value, onChange, requiredTags, id, ariaLabel, ariaDescribedBy, className, autoFocus, placeholder, dir, onKeyDown },
  ref,
) {
  const { t } = useI18n();
  const el = useRef<HTMLDivElement>(null);
  const lastValue = useRef<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const requiredKey = requiredTags.join("|");
  const required = useMemo(() => (requiredKey ? requiredKey.split("|") : []), [requiredKey]);

  const render = useCallback(
    (v: string) => {
      const root = el.current;
      if (!root) return;
      root.replaceChildren();
      const remaining = new Map<string, number>();
      for (const tag of required) remaining.set(tag, (remaining.get(tag) ?? 0) + 1);
      for (const p of tokenize(v)) {
        if (p.type === "text") root.append(document.createTextNode(p.value));
        else {
          const left = remaining.get(p.value) ?? 0;
          remaining.set(p.value, left - 1);
          root.append(chipFor(p.value, left <= 0));
        }
      }
      lastValue.current = v;
    },
    [required],
  );

  // Sync from props only when the value changed outside the editor.
  useEffect(() => {
    if (value !== lastValue.current) render(value);
  }, [value, render]);

  useEffect(() => {
    if (autoFocus) focusEnd(el.current);
  }, [autoFocus]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 2500);
    return () => clearTimeout(timer);
  }, [notice]);

  /** A chip may be removed only if the target has more copies of it than the source needs. */
  const isProtected = useCallback(
    (chip: HTMLElement): boolean => {
      const token = chip.dataset.tag!;
      const have = tagsOf(serializeNodes(el.current?.childNodes ?? [])).filter((tagsOf) => tagsOf === token).length;
      const need = required.filter((tag) => tag === token).length;
      return have <= need;
    },
    [required],
  );

  const rangeTouchesProtectedChip = useCallback(
    (range: Range): boolean => {
      const root = el.current;
      if (!root) return false;
      for (const chip of root.querySelectorAll<HTMLElement>("[data-tag]")) {
        if (range.intersectsNode(chip) && isProtected(chip)) {
          // A collapsed range touching a chip boundary is fine for insertion.
          if (range.collapsed) continue;
          return true;
        }
      }
      return false;
    },
    [isProtected],
  );

  const emit = useCallback(() => {
    const root = el.current;
    if (!root) return;
    const next = serializeNodes(root.childNodes);
    const before = diffTags(required, tagsOf(lastValue.current ?? ""));
    const after = diffTags(required, tagsOf(next));
    if (after.missing.length > before.missing.length) {
      // Safety net: a required tag disappeared through a path we did not intercept.
      render(lastValue.current ?? "");
      focusEnd(root);
      setNotice(t("components.tagEditor.tagsCannotBeDeletedEdit"));
      return;
    }
    // Refresh the extra flag on chips.
    const remaining = new Map<string, number>();
    for (const tag of required) remaining.set(tag, (remaining.get(tag) ?? 0) + 1);
    for (const chip of root.querySelectorAll<HTMLElement>("[data-tag]")) {
      const left = remaining.get(chip.dataset.tag!) ?? 0;
      remaining.set(chip.dataset.tag!, left - 1);
      chip.dataset.extra = String(left <= 0);
    }
    lastValue.current = next;
    onChange(next);
  }, [onChange, render, required, t]);

  useImperativeHandle(
    ref,
    () => ({
      focus: () => focusEnd(el.current),
      selectionSpan: () => {
        const root = el.current;
        const sel = window.getSelection();
        if (!root || !sel || sel.rangeCount === 0) return null;
        const r = sel.getRangeAt(0);
        if (!root.contains(r.startContainer) || !root.contains(r.endContainer)) return null;
        const pre = document.createRange();
        pre.selectNodeContents(root);
        pre.setEnd(r.startContainer, r.startOffset);
        const start = serializeNodes(pre.cloneContents().childNodes).length;
        const len = serializeNodes(r.cloneContents().childNodes).length;
        return [start, start + len];
      },
      insertTag: (token: string) => {
        const root = el.current;
        if (!root) return;
        root.focus();
        const sel = window.getSelection();
        let range: Range;
        if (sel && sel.rangeCount > 0 && root.contains(sel.getRangeAt(0).startContainer)) {
          range = sel.getRangeAt(0);
          range.collapse(false);
        } else {
          range = document.createRange();
          range.selectNodeContents(root);
          range.collapse(false);
        }
        const chip = chipFor(token, false);
        range.insertNode(chip);
        range.setStartAfter(chip);
        range.collapse(true);
        sel?.removeAllRanges();
        sel?.addRange(range);
        emit();
      },
    }),
    [emit],
  );

  const onBeforeInput = (e: React.FormEvent<HTMLDivElement>) => {
    const ne = e.nativeEvent as InputEvent;
    const type = ne.inputType ?? "";
    if (type === "insertParagraph" || type === "insertLineBreak" || type.startsWith("format") || type === "insertFromDrop") {
      e.preventDefault();
      return;
    }
    const ranges = typeof ne.getTargetRanges === "function" ? ne.getTargetRanges() : [];
    const live: Range[] = ranges.map((sr) => {
      const r = document.createRange();
      r.setStart(sr.startContainer, sr.startOffset);
      r.setEnd(sr.endContainer, sr.endOffset);
      return r;
    });
    if (live.length === 0) {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) live.push(sel.getRangeAt(0));
    }
    if (live.some(rangeTouchesProtectedChip)) {
      e.preventDefault();
      setNotice(t("components.tagEditor.tagsCannotBeDeletedOr"));
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
    e.preventDefault();
    const text = e.clipboardData.getData("text/plain").replace(/\r?\n/g, " ");
    // execCommand keeps native undo; it fires beforeinput so the chip guard still applies.
    document.execCommand("insertText", false, text);
  };

  const onCopy = (e: React.ClipboardEvent<HTMLDivElement>) => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    e.preventDefault();
    e.clipboardData.setData("text/plain", serializeNodes(sel.getRangeAt(0).cloneContents().childNodes));
  };

  return (
    <div className="relative">
      <div
        ref={el}
        id={id}
        role="textbox"
        aria-multiline="true"
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        contentEditable
        suppressContentEditableWarning
        spellCheck
        dir={dir}
        data-placeholder={placeholder}
        onBeforeInput={onBeforeInput}
        onInput={emit}
        onPaste={onPaste}
        onCopy={onCopy}
        onCut={(e) => {
          onCopy(e);
          document.execCommand("delete");
        }}
        onDrop={(e) => e.preventDefault()}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !(e.metaKey || e.ctrlKey)) e.preventDefault();
          onKeyDown?.(e);
        }}
        className={cn(
          "tag-editor min-h-16 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-[14.5px] leading-relaxed text-fg shadow-card focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-ring",
          className,
        )}
      />
      {notice && (
        <div role="status" className="absolute -bottom-6 left-0 text-[12px] font-medium text-warn">
          {notice}
        </div>
      )}
    </div>
  );
});

function focusEnd(root: HTMLElement | null) {
  if (!root) return;
  root.focus();
  const sel = window.getSelection();
  if (!sel) return;
  const r = document.createRange();
  r.selectNodeContents(root);
  r.collapse(false);
  sel.removeAllRanges();
  sel.addRange(r);
}

/** Validation summary + one-click re-insertion of missing tags. */
export function TagStatus({
  required,
  value,
  onInsert,
}: {
  required: string[];
  value: string;
  onInsert?: (token: string) => void;
}) {
  const { t } = useI18n();
  const { missing, extra } = diffTags(required, tagsOf(value));
  if (missing.length === 0 && extra.length === 0) {
    return required.length > 0 ? <p className="text-[12px] text-ok">{t("components.tagEditor.allTagsInPlace", { count: required.length })}</p> : null;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
      {missing.length > 0 && (
        <>
          <span className="font-medium text-danger">{t("components.tagEditor.missingTagsSaveBlocked")}</span>
          {missing.map((tag, i) =>
            onInsert ? (
              <button
                key={`${tag}-${i}`}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onInsert(tag)}
                className="tag-chip cursor-pointer hover:opacity-80"
                title={t("components.tagEditor.insertAtCursor")}
              >
                + {tagLabel(tag)}
              </button>
            ) : (
              <span key={`${tag}-${i}`} className="tag-chip">
                {tagLabel(tag)}
              </span>
            ),
          )}
        </>
      )}
      {extra.length > 0 && (
        <span className="font-medium text-danger">
          {t("components.tagEditor.extraTagsNotInSource", { value: extra.map(tagLabel).join(" ") })}
        </span>
      )}
    </div>
  );
}

export function tagsValid(required: string[], value: string): boolean {
  const d = diffTags(required, tagsOf(value));
  return d.missing.length === 0 && d.extra.length === 0;
}
