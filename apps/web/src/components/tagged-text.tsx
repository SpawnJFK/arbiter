"use client";

import { useI18n } from "@/lib/i18n/client";
import { cn } from "@/lib/cn";
import { tagLabel, tokenize } from "@/lib/tags";

/** Read-only rendering of tagged text with tags as small chips. */
export function TaggedText({ value, className, dir }: { value: string | null | undefined; className?: string; dir?: "ltr" | "rtl" | "auto" }) {
  const { t } = useI18n();
  if (!value) return <span className={cn("italic text-faint", className)}>{t("components.taggedText.noTranslationYet")}</span>;
  return (
    <span className={cn("whitespace-pre-wrap break-words", className)} dir={dir}>
      {tokenize(value).map((p, i) =>
        p.type === "tag" ? (
          <span key={i} className="tag-chip" title={t("components.taggedText.inlineTag", { value: p.value })}>
            {tagLabel(p.value)}
          </span>
        ) : (
          <span key={i}>{p.value}</span>
        ),
      )}
    </span>
  );
}
