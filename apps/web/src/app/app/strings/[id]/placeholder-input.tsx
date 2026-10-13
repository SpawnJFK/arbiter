"use client";

import { useRef } from "react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n/client";
import { placeholderDiff } from "@/lib/strings";

/**
 * Text area for one string value with the source's placeholders as chips (like the segment tag
 * editor): click a chip to insert it at the cursor. Chips turn red when the value misses them,
 * and placeholders the source does not have are listed as extra, so a broken placeholder is
 * visible before the server's QA blocks it.
 */
export function PlaceholderInput({
  id,
  value,
  onChange,
  source,
  placeholders,
  maxLength,
  dir,
  disabled,
  label,
  optionalMissing,
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  source: string;
  placeholders: string[];
  maxLength?: number | null;
  dir?: "ltr" | "rtl" | "auto";
  disabled?: boolean;
  label: string;
  optionalMissing?: boolean;
}) {
  const { t } = useI18n();
  const ref = useRef<HTMLTextAreaElement>(null);
  const { missing, added } = placeholderDiff(source, value);
  const missingSet = new Set(missing);
  const chips = Array.from(new Set(placeholders.filter((p) => p.length < 40)));

  function insert(text: string) {
    const el = ref.current;
    if (!el) return onChange(value + text);
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const next = value.slice(0, start) + text + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + text.length, start + text.length);
    });
  }

  const tooLong = maxLength != null && value.length > maxLength;
  return (
    <div>
      <textarea
        ref={ref}
        id={id}
        aria-label={label}
        dir={dir ?? "auto"}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.min(8, Math.max(2, Math.ceil(value.length / 60)))}
        className={cn(
          "w-full resize-y rounded-md border bg-surface px-2.5 py-2 text-sm text-fg focus-visible:outline-2 focus-visible:outline-ring",
          tooLong || (!optionalMissing && missing.length) || added.length ? "border-danger" : "border-border-strong",
        )}
      />
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
        {chips.map((p) => (
          <button
            key={p}
            type="button"
            disabled={disabled}
            onClick={() => insert(p)}
            data-extra={missingSet.has(p) && !optionalMissing ? "true" : "false"}
            className="tag-chip cursor-pointer"
            style={{ fontSize: "12px", height: "1.7em", padding: "0 0.45em" }}
            title={missingSet.has(p) ? t("app.strings.editor.placeholderMissing") : t("app.strings.editor.insertPlaceholder")}
          >
            {p}
          </button>
        ))}
        {added.length > 0 && (
          <span className="text-danger">{t("app.strings.editor.extraPlaceholders", { list: added.join(" ") })}</span>
        )}
        {maxLength != null && (
          <span className={cn("ml-auto tabular", tooLong ? "text-danger" : "text-muted")}>
            {value.length}/{maxLength}
          </span>
        )}
      </div>
    </div>
  );
}
