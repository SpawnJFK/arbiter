import { dateTime, relative } from "@/lib/format";

/** <time> with an absolute UTC title; relative text may differ by seconds between server and client. */
export function Time({ iso, mode = "absolute" }: { iso: string | null | undefined; mode?: "absolute" | "relative" }) {
  if (!iso) return <span className="text-faint">–</span>;
  return (
    <time dateTime={iso} title={dateTime(iso)} suppressHydrationWarning className="tabular">
      {mode === "relative" ? relative(iso) : dateTime(iso)}
    </time>
  );
}
