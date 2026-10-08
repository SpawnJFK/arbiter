"use client";

import { useI18n } from "@/lib/i18n/client";
import { Fragment } from "react";
import { cn } from "@/lib/cn";
import type { Translator } from "@/lib/i18n/core";
import { STEP_META, type StepStatus } from "@/lib/workflow";
import type { WorkflowStep } from "@/lib/types";

const GROUP: Record<string, string> = {
  machine: "border-info/40 bg-info-subtle text-info",
  ai: "border-accent/40 bg-accent-subtle text-accent",
  human: "border-violet/40 bg-violet-subtle text-violet",
  client: "border-warn/40 bg-warn-subtle text-warn",
  end: "border-ok/40 bg-ok-subtle text-ok",
};

function paramText(t: Translator, s: WorkflowStep): string | null {
  const p = s.params ?? {};
  if (s.kind === "mt" && p.engine) return p.engine;
  if (s.kind === "qe" && typeof p.threshold === "number") return t("components.workflowPipeline.threshold", { threshold: p.threshold });
  if ((s.kind === "human_review" || s.kind === "second_review") && p.min_level) return t("components.workflowPipeline.minLevel", { level: t.enumLabel(p.min_level) });
  return null;
}

/** Boxes-and-arrows view of a workflow. With `statuses`, shows done / current / to do. */
export function WorkflowPipeline({ steps, statuses, compact, className }: { steps: WorkflowStep[]; statuses?: StepStatus[]; compact?: boolean; className?: string }) {
  const { t } = useI18n();
  return (
    <ol className={cn("flex flex-wrap items-center gap-y-2", className)} aria-label={t("components.workflowPipeline.workflowSteps")}>
      {steps.map((s, i) => {
        const meta = STEP_META[s.kind];
        const st = statuses?.[i];
        const p = paramText(t, s);
        return (
          <Fragment key={`${s.kind}-${i}`}>
            <li
              aria-current={st === "current" ? "step" : undefined}
              title={meta ? t(meta.help) : undefined}
              className={cn(
                "relative flex flex-col rounded-md border px-2.5 py-1.5 text-[12.5px] leading-tight",
                statuses
                  ? st === "done"
                    ? "border-ok/40 bg-ok-subtle text-ok"
                    : st === "current"
                      ? "border-accent bg-accent text-accent-fg shadow-card ring-2 ring-accent/25"
                      : "border-border bg-surface text-muted"
                  : GROUP[meta?.group ?? "machine"],
              )}
            >
              <span className="flex items-center gap-1 font-medium">
                {st === "done" && <span aria-hidden="true">✓</span>}
                {meta ? t(compact ? meta.short : meta.label) : s.kind}
              </span>
              {p && !compact && <span className="mt-0.5 text-[11px] opacity-80">{p}</span>}
              {st && <span className="sr-only">{st === "done" ? t("components.workflowPipeline.done") : st === "current" ? t("components.workflowPipeline.currentStep") : t("components.workflowPipeline.toDo")}</span>}
            </li>
            {i < steps.length - 1 && (
              <li aria-hidden="true" className="flex items-center px-1 text-faint">
                <svg viewBox="0 0 20 10" className="h-2.5 w-5">
                  <path d="M0 5h16M12 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </li>
            )}
          </Fragment>
        );
      })}
    </ol>
  );
}
