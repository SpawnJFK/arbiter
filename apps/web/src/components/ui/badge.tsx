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
  quoted: "neutral",
  running: "info",
  review: "violet",
  ready: "info",
  merging: "info",
  delivered: "ok",
  settled: "ok",
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
  auto_approved: "ok",
  needs_review: "warn",
  in_review: "violet",
  reviewed: "ok",
  delivered: "ok",
};

/** Segment state; "reviewed" with origin "editor" is shown as AI reviewed (contract). Blocked shows via DecisionBadge. */
export function SegmentStateBadge({
  state,
  origin,
}: {
  state: SegmentState;
  /** Accepted for call-site symmetry; blocked is rendered by DecisionBadge. */
  decision?: string | null;
  origin?: string | null;
}) {
  if (state === "reviewed" && origin === "editor") return <Badge tone="accent">AI reviewed</Badge>;
  return <Badge tone={SEG_TONE[state] ?? "neutral"}>{humanize(state)}</Badge>;
}

const DECISION: Record<Decision, { tone: Tone; label: string; title: string }> = {
  auto_approve: { tone: "ok", label: "Auto", title: "Cleared the threshold, shipped without a human" },
  senate: { tone: "accent", label: "Senate", title: "Decided by the AI senate" },
  review: { tone: "violet", label: "Human", title: "Routed to a human reviewer" },
  blocked: { tone: "danger", label: "Blocked", title: "A hard check failed; needs a domain expert or your team" },
  ai_edit: { tone: "accent", label: "AI edit", title: "Queued for the AI editor" },
  ai_reviewed: { tone: "accent", label: "AI reviewed", title: "Revised by the AI editor" },
  ai_fallback: { tone: "warn", label: "AI fallback", title: "No reviewer was available; AI review per your policy (disclosed)" },
  unreviewed: { tone: "warn", label: "Unreviewed", title: "Delivered without the planned review per your policy (disclosed)" },
  reviewed: { tone: "ok", label: "Reviewed", title: "A human decided" },
};

export function DecisionBadge({ decision }: { decision: Decision | string | null }) {
  if (!decision) return <span className="text-faint">–</span>;
  const d = DECISION[decision as Decision] ?? { tone: "neutral" as Tone, label: humanize(decision), title: decision };
  return (
    <Badge tone={d.tone} title={d.title}>
      {d.label}
    </Badge>
  );
}

export function decisionLabel(d: string): string {
  return DECISION[d as Decision]?.label ?? humanize(d);
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
  const tone: Tone = ["active", "passed", "paid", "answered", "decided", "upheld", "available", "settled", "sent"].includes(s)
    ? "ok"
    : ["suspended", "failed", "rejected", "overturned", "banned", "blocked", "expired"].includes(s)
      ? "danger"
      : ["testing", "pending", "open", "applied", "held", "accrued", "demoted"].includes(s)
        ? "warn"
        : "neutral";
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}
