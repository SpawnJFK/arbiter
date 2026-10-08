"use client";

import { useI18n } from "@/lib/i18n/client";

/** <time> with an absolute UTC title; relative text may differ by seconds between server and client. */
export function Time({ iso, mode = "absolute" }: { iso: string | null | undefined; mode?: "absolute" | "relative" }) {
  const { f } = useI18n();
  if (!iso) return <span className="text-faint">–</span>;
  return (
    <time dateTime={iso} title={f.dateTime(iso)} suppressHydrationWarning className="tabular">
      {mode === "relative" ? f.relative(iso) : f.dateTime(iso)}
    </time>
  );
}
