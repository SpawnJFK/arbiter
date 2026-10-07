import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { humanize, score as fmtScore } from "@/lib/format";
import type { Decision, JobState, SegmentState, TermKind } from "@/lib/types";

export type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info" | "violet";

const tones: Record<Tone, string> = {
  neutral: "bg-subtle text-muted border-border",
  accent: "bg-accent-subtle text-accent border-transparent",
  ok: "bg-ok-subtle text-ok border-transparent",
  warn: "bg-warn-subtle text-warn border-transparent",
  danger: "bg-danger-subtle text-danger border-transparent",
  info: "bg-info-subtle text-info border-transparent",
  violet: "bg-violet-subtle text-violet border-transparent",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  dot,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-[5px] border px-1.5 text-[12px] font-medium leading-none",
        tones[tone],
        className,
      )}
    >
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />}
      {children}
    </span>
  );
}

const JOB_TONE: Record<JobState, Tone> = {
  draft: "neutral",
  queued: "neutral",
  preparing: "info",
  translating: "info",
  scoring: "info",
  review: "violet",
  merging: "info",
  delivered: "ok",
  failed: "danger",
  cancelled: "neutral",
  disputed: "warn",
};

export function JobStateBadge({ state }: { state: JobState }) {
  return (
    <Badge tone={JOB_TONE[state] ?? "neutral"} dot>
      {humanize(state)}
    </Badge>
  );
}

const SEG_TONE: Record<SegmentState, Tone> = {
  pending: "neutral",
  translated: "neutral",
  scored: "info",
  auto_approved: "ok",
  in_review: "violet",
  reviewed: "ok",
  ai_reviewed: "accent",
  approved: "ok",
  delivered: "ok",
  needs_review: "warn",
  blocked: "danger",
};

export function SegmentStateBadge({ state }: { state: SegmentState }) {
  return <Badge tone={SEG_TONE[state] ?? "neutral"}>{humanize(state)}</Badge>;
}

const DECISION: Record<Decision, { tone: Tone; label: string }> = {
  auto_approve: { tone: "ok", label: "Auto" },
  senate: { tone: "accent", label: "Senate" },
  review: { tone: "violet", label: "Human" },
  blocked: { tone: "danger", label: "Blocked" },
};

export function DecisionBadge({ decision }: { decision: Decision | null }) {
  if (!decision) return <span className="text-faint">–</span>;
  const d = DECISION[decision] ?? { tone: "neutral" as Tone, label: humanize(decision) };
  return <Badge tone={d.tone}>{d.label}</Badge>;
}

/**
 * QE score badge on the backend's 0-100 scale (values <= 1 are treated as 0..1 and scaled).
 * Green: clears threshold + band (auto zone). Amber: inside the senate band. Red: review zone.
 */
export function QeBadge({ value, threshold, band = 8 }: { value: number | null; threshold?: number | null; band?: number }) {
  if (value === null || value === undefined) return <span className="text-faint">–</span>;
  const v = qe100(value);
  const t = qe100(threshold ?? 78);
  const tone: Tone = v >= t + band ? "ok" : v > t - band ? "warn" : "danger";
  const label = tone === "ok" ? "clears threshold + band" : tone === "warn" ? "inside the senate band" : "below the band, human review";
  return (
    <Badge tone={tone} className="tabular font-mono" title={`QE ${fmtScore(v)}: ${label} (threshold ${fmtScore(t)}, band ±${band})`}>
      {fmtScore(v)}
    </Badge>
  );
}

export function qe100(v: number): number {
  return v <= 1 ? v * 100 : v;
}

const KIND: Record<TermKind, { tone: Tone; label: string }> = {
  mandatory: { tone: "accent", label: "Mandatory" },
  preferred: { tone: "info", label: "Preferred" },
  forbidden: { tone: "danger", label: "Forbidden" },
  do_not_translate: { tone: "neutral", label: "Do not translate" },
};

export function TermKindBadge({ kind }: { kind: TermKind }) {
  const k = KIND[kind] ?? { tone: "neutral" as Tone, label: humanize(kind) };
  return <Badge tone={k.tone}>{k.label}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const tone: Tone = ["active", "passed", "paid", "answered", "decided", "upheld", "available"].includes(s)
    ? "ok"
    : ["suspended", "failed", "rejected", "overturned"].includes(s)
      ? "danger"
      : ["testing", "pending", "open", "applied", "held"].includes(s)
        ? "warn"
        : "neutral";
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}
