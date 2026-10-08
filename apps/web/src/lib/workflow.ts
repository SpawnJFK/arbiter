// Workflow step metadata and client-side validation. The rules mirror
// services/api/arbiter/agency/workflows.py validate_steps(); the API stays the authority and
// its 422 message is shown when it disagrees.
import en from "../../messages/en.json";
import { createTranslator, k, type Messages, type Translator } from "./i18n/core";
import type { Job, StepKind, Tier, WorkflowStep } from "./types";

const ENGLISH = createTranslator("en", en as Messages);

/** Step labels are message keys (translate with `t`). */
export const STEP_META: Record<StepKind, { label: string; short: string; help: string; group: "machine" | "ai" | "human" | "client" | "end" }> = {
  tm: { label: k("step.tm.label"), short: k("step.tm.short"), help: k("step.tm.help"), group: "machine" },
  mt: { label: k("step.mt.label"), short: k("step.mt.short"), help: k("step.mt.help"), group: "machine" },
  translation_senate: { label: k("step.translation_senate.label"), short: k("step.translation_senate.short"), help: k("step.translation_senate.help"), group: "ai" },
  qe: { label: k("step.qe.label"), short: k("step.qe.short"), help: k("step.qe.help"), group: "ai" },
  senate: { label: k("step.senate.label"), short: k("step.senate.short"), help: k("step.senate.help"), group: "ai" },
  ai_review: { label: k("step.ai_review.label"), short: k("step.ai_review.short"), help: k("step.ai_review.help"), group: "ai" },
  human_review: { label: k("step.human_review.label"), short: k("step.human_review.short"), help: k("step.human_review.help"), group: "human" },
  second_review: { label: k("step.second_review.label"), short: k("step.second_review.short"), help: k("step.second_review.help"), group: "human" },
  client_review: { label: k("step.client_review.label"), short: k("step.client_review.short"), help: k("step.client_review.help"), group: "client" },
  delivery: { label: k("step.delivery.label"), short: k("step.delivery.short"), help: k("step.delivery.help"), group: "end" },
};

const TRANSLATION: StepKind[] = ["tm", "mt", "translation_senate"];
const REVIEWS: StepKind[] = ["senate", "ai_review", "human_review", "second_review", "client_review"];
const HUMANS: StepKind[] = ["human_review", "second_review"];

/** Every broken rule, in the API's wording (empty = valid). Pass `t` for the UI locale; defaults to English. */
export function validateWorkflow(steps: WorkflowStep[], tier: Tier, regulated = false, t: Translator = ENGLISH): string[] {
  const out: string[] = [];
  const kinds = steps.map((s) => s.kind);
  const pos = new Map<StepKind, number>();
  kinds.forEach((k, i) => {
    if (!pos.has(k)) pos.set(k, i);
  });
  const dupes = [...new Set(kinds.filter((k, i) => kinds.indexOf(k) !== i))];
  if (dupes.length) out.push(t("workflow.problem.duplicate", { steps: dupes.map((x) => t(STEP_META[x].short)).join(", ") }));
  if (!TRANSLATION.some((k) => pos.has(k))) out.push(t("workflow.problem.needsTranslation"));
  if (!pos.has("delivery") || kinds[kinds.length - 1] !== "delivery") out.push(t("workflow.problem.deliveryLast"));
  const reviews = kinds.filter((k) => REVIEWS.includes(k));
  const qe = pos.get("qe");
  if (reviews.length && qe === undefined) out.push(t("workflow.problem.qeBeforeReview"));
  if (qe !== undefined) {
    const late = TRANSLATION.filter((k) => (pos.get(k) ?? -1) > qe);
    if (late.length) out.push(t("workflow.problem.translationBeforeQe", { steps: late.map((x) => t(STEP_META[x].short)).join(", ") }));
    const early = reviews.filter((k) => (pos.get(k) ?? 99) < qe);
    if (early.length) out.push(t("workflow.problem.reviewBeforeQe", { steps: early.map((x) => t(STEP_META[x].short)).join(", ") }));
  }
  if (pos.has("second_review") && (!pos.has("human_review") || pos.get("human_review")! > pos.get("second_review")!))
    out.push(t("workflow.problem.secondNeedsFirst"));
  if (!pos.has("mt") && !pos.has("translation_senate") && !pos.has("human_review") && pos.has("tm"))
    out.push(t("workflow.problem.tmOnlyNeedsHuman"));
  const humans = HUMANS.filter((k) => pos.has(k));
  if (tier === "full" && !pos.has("human_review")) out.push(t("workflow.problem.fullNeedsHuman"));
  if (tier === "auto" && (humans.length || pos.has("ai_review"))) out.push(t("workflow.problem.autoNoReview"));
  if (tier === "ai_review" && humans.length) out.push(t("workflow.problem.aiReviewNoHuman"));
  if (regulated && (tier === "auto" || tier === "ai_review")) out.push(t("workflow.problem.regulatedTier"));
  for (const s of steps) {
    const thr = s.params?.threshold;
    if (s.kind === "qe" && thr !== undefined && thr !== null && !(thr >= 0 && thr <= 100)) out.push(t("workflow.problem.qeThreshold"));
  }
  return [...new Set(out)];
}

/** Clean params before sending: drop empty values the API would reject. */
export function cleanSteps(steps: WorkflowStep[]): WorkflowStep[] {
  return steps.map((s) => {
    const params: WorkflowStep["params"] = {};
    if (s.kind === "mt" && s.params?.engine?.trim()) params.engine = s.params.engine.trim();
    if (s.kind === "qe" && typeof s.params?.threshold === "number" && !Number.isNaN(s.params.threshold)) params.threshold = s.params.threshold;
    if ((s.kind === "human_review" || s.kind === "second_review") && s.params?.min_level) params.min_level = s.params.min_level;
    return { kind: s.kind, params };
  });
}

export type StepStatus = "done" | "current" | "todo";

/**
 * Where a job is in its workflow. The API has no explicit pointer, so it is derived from the
 * job state: running = translation and scoring, review = review steps, ready/awaiting client =
 * client approval, merging = delivery, delivered = everything done.
 */
export function stepStatuses(job: Pick<Job, "state" | "awaiting_client_approval" | "client_approved_at">, steps: WorkflowStep[]): StepStatus[] {
  const kinds = steps.map((s) => s.kind);
  const idx = (pred: (k: StepKind) => boolean) => kinds.findIndex(pred);
  let current = -1;
  switch (job.state) {
    case "delivered":
    case "settled":
    case "disputed":
      return steps.map(() => "done");
    case "draft":
    case "quoted":
      current = 0;
      break;
    case "running": {
      const qe = kinds.indexOf("qe");
      current = qe >= 0 ? qe : 0;
      break;
    }
    case "review":
      current = idx((k) => k === "human_review" || k === "second_review" || k === "senate" || k === "ai_review");
      break;
    case "ready":
      current = job.awaiting_client_approval ? kinds.indexOf("client_review") : kinds.indexOf("delivery");
      break;
    case "merging":
      current = kinds.indexOf("delivery");
      break;
    default:
      current = -1;
  }
  if (job.awaiting_client_approval) current = kinds.indexOf("client_review");
  if (current < 0) return steps.map(() => "todo");
  return steps.map((_, i) => (i < current ? "done" : i === current ? "current" : "todo"));
}
