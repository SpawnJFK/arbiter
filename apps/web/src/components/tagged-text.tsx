import { cn } from "@/lib/cn";
import { tagLabel, tokenize } from "@/lib/tags";

/** Read-only rendering of tagged text with tags as small chips. */
export function TaggedText({ value, className, dir }: { value: string; className?: string; dir?: "ltr" | "rtl" | "auto" }) {
  return (
    <span className={cn("whitespace-pre-wrap break-words", className)} dir={dir}>
      {tokenize(value).map((p, i) =>
        p.type === "tag" ? (
          <span key={i} className="tag-chip" title={`Inline tag ${p.value}`}>
            {tagLabel(p.value)}
          </span>
        ) : (
          <span key={i}>{p.value}</span>
        ),
      )}
    </span>
  );
}
