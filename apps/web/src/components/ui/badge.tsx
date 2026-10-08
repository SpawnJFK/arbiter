"use client";

import { k, type Translator } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
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
  const { t } = useI18n();
  return (
    <Badge tone={JOB_TONE[state] ?? "neutral"} dot>
      {t.enumLabel(state)}
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
  const { t } = useI18n();
  if (state === "reviewed" && origin === "editor") return <Badge tone="accent">{t("components.badge.aiReviewed")}</Badge>;
  return <Badge tone={SEG_TONE[state] ?? "neutral"}>{t.enumLabel(state)}</Badge>;
}

const DECISION: Record<Decision, { tone: Tone; label: string; title: string }> = {
  auto_approve: { tone: "ok", label: k("components.badge.auto"), title: k("components.badge.clearedTheThresholdShippedWithout") },
  senate: { tone: "accent", label: k("components.badge.senate"), title: k("components.badge.decidedByTheAiSenate") },
  review: { tone: "violet", label: k("components.badge.human"), title: k("components.badge.routedToAHumanReviewer") },
  blocked: { tone: "danger", label: k("components.badge.blocked"), title: k("components.badge.aHardCheckFailedNeeds") },
  ai_edit: { tone: "accent", label: k("components.badge.aiEdit"), title: k("components.badge.queuedForTheAiEditor") },
  ai_reviewed: { tone: "accent", label: k("components.badge.aiReviewed"), title: k("components.badge.revisedByTheAiEditor") },
  ai_fallback: { tone: "warn", label: k("components.badge.aiFallback"), title: k("components.badge.noReviewerWasAvailableAi") },
  unreviewed: { tone: "warn", label: k("components.badge.unreviewed"), title: k("components.badge.deliveredWithoutThePlannedReview") },
  reviewed: { tone: "ok", label: k("components.badge.reviewed"), title: k("components.badge.aHumanDecided") },
};

export function DecisionBadge({ decision }: { decision: Decision | string | null }) {
  const { t } = useI18n();
  if (!decision) return <span className="text-faint">–</span>;
  const d = DECISION[decision as Decision];
  return (
    <Badge tone={d?.tone ?? "neutral"} title={d ? t(d.title) : decision}>
      {decisionLabel(t, decision)}
    </Badge>
  );
}

export function decisionLabel(t: Translator, d: string): string {
  const known = DECISION[d as Decision];
  return known ? t(known.label) : t.enumLabel(d);
}

/**
 * QE score badge on the backend's 0-100 scale (values <= 1 are treated as 0..1 and scaled).
 * Green: clears threshold + band (auto zone). Amber: inside the senate band. Red: review zone.
 */
export function QeBadge({ value, threshold, band = 8 }: { value: number | null; threshold?: number | null; band?: number }) {
  const { t, f } = useI18n();
  if (value === null || value === undefined) return <span className="text-faint">–</span>;
  const v = qe100(value);
  const thr = qe100(threshold ?? 78);
  const tone: Tone = v >= thr + band ? "ok" : v > thr - band ? "warn" : "danger";
  const label = tone === "ok" ? t("components.badge.qe.clears") : tone === "warn" ? t("components.badge.qe.inBand") : t("components.badge.qe.belowBand");
  return (
    <Badge tone={tone} className="tabular font-mono" title={t("components.badge.qeThresholdBand", { v: f.score(v), label, thr: f.score(thr), band })}>
      {f.score(v)}
    </Badge>
  );
}

export function qe100(v: number): number {
  return v <= 1 ? v * 100 : v;
}

const KIND: Record<TermKind, { tone: Tone; label: string }> = {
  mandatory: { tone: "accent", label: k("components.badge.mandatory") },
  preferred: { tone: "info", label: k("components.badge.preferred") },
  forbidden: { tone: "danger", label: k("components.badge.forbidden") },
  do_not_translate: { tone: "neutral", label: k("components.badge.doNotTranslate") },
};

export function TermKindBadge({ kind }: { kind: TermKind }) {
  const { t } = useI18n();
  const known = KIND[kind];
  return <Badge tone={known?.tone ?? "neutral"}>{known ? t(known.label) : t.enumLabel(kind)}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const s = status.toLowerCase();
  const tone: Tone = ["active", "passed", "paid", "answered", "decided", "upheld", "available", "settled", "sent"].includes(s)
    ? "ok"
    : ["suspended", "failed", "rejected", "overturned", "banned", "blocked", "expired"].includes(s)
      ? "danger"
      : ["testing", "pending", "open", "applied", "held", "accrued", "demoted"].includes(s)
        ? "warn"
        : "neutral";
  return <Badge tone={tone}>{t.enumLabel(status)}</Badge>;
}
