// Workflow step metadata and client-side validation. The rules mirror
// services/api/arbiter/agency/workflows.py validate_steps(); the API stays the authority and
// its 422 message is shown when it disagrees.
import type { Job, StepKind, Tier, WorkflowStep } from "./types";

export const STEP_META: Record<StepKind, { label: string; short: string; help: string; group: "machine" | "ai" | "human" | "client" | "end" }> = {
  tm: { label: "TM pre-translation", short: "TM", help: "Reuse context and exact matches from your translation memory.", group: "machine" },
  mt: { label: "Machine translation", short: "MT", help: "Translate with an engine; optionally pin one engine.", group: "machine" },
  translation_senate: { label: "Translation senate", short: "Best-of-N", help: "Several engines translate; the senate picks the best candidate.", group: "ai" },
  qe: { label: "Quality estimation", short: "QE", help: "Score every segment; optionally override the threshold (0 to 100).", group: "ai" },
  senate: { label: "Review senate", short: "Senate", help: "AI judges vote on segments inside the uncertainty band.", group: "ai" },
  ai_review: { label: "AI review", short: "AI review", help: "Senate plus the AI editor instead of a human (AI review tier).", group: "ai" },
  human_review: { label: "Human review", short: "Review", help: "A vetted reviewer decides; optionally require a minimum level.", group: "human" },
  second_review: { label: "Second review", short: "2nd review", help: "A second, senior reviewer checks after the first one.", group: "human" },
  client_review: { label: "Client approval", short: "Client", help: "The job waits for the client's approval before delivery.", group: "client" },
  delivery: { label: "Delivery", short: "Delivery", help: "Merge into the original format and deliver.", group: "end" },
};

const TRANSLATION: StepKind[] = ["tm", "mt", "translation_senate"];
const REVIEWS: StepKind[] = ["senate", "ai_review", "human_review", "second_review", "client_review"];
const HUMANS: StepKind[] = ["human_review", "second_review"];

/** Every broken rule, in the API's wording (empty = valid). */
export function validateWorkflow(steps: WorkflowStep[], tier: Tier, regulated = false): string[] {
  const out: string[] = [];
  const kinds = steps.map((s) => s.kind);
  const pos = new Map<StepKind, number>();
  kinds.forEach((k, i) => {
    if (!pos.has(k)) pos.set(k, i);
  });
  const dupes = [...new Set(kinds.filter((k, i) => kinds.indexOf(k) !== i))];
  if (dupes.length) out.push(`Each step may appear once: ${dupes.join(", ")} repeated.`);
  if (!TRANSLATION.some((k) => pos.has(k))) out.push("A workflow must contain MT or TM.");
  if (!pos.has("delivery") || kinds[kinds.length - 1] !== "delivery") out.push("Delivery must be the last step.");
  const reviews = kinds.filter((k) => REVIEWS.includes(k));
  const qe = pos.get("qe");
  if (reviews.length && qe === undefined) out.push("QE must come before any review step.");
  if (qe !== undefined) {
    const late = TRANSLATION.filter((k) => (pos.get(k) ?? -1) > qe);
    if (late.length) out.push(`${late.map((k) => STEP_META[k].short).join(", ")} must come before QE.`);
    const early = reviews.filter((k) => (pos.get(k) ?? 99) < qe);
    if (early.length) out.push(`QE must come before any review step (${early.map((k) => STEP_META[k].short).join(", ")} is before QE).`);
  }
  if (pos.has("second_review") && (!pos.has("human_review") || pos.get("human_review")! > pos.get("second_review")!))
    out.push("Second review needs a human review step before it.");
  if (!pos.has("mt") && !pos.has("translation_senate") && !pos.has("human_review") && pos.has("tm"))
    out.push("A TM-only workflow needs human review (unmatched segments are translated by a person).");
  const humans = HUMANS.filter((k) => pos.has(k));
  if (tier === "full" && !pos.has("human_review")) out.push("Tier Full needs a human review step.");
  if (tier === "auto" && (humans.length || pos.has("ai_review"))) out.push("Tier Auto cannot contain human review, second review or AI review.");
  if (tier === "ai_review" && humans.length) out.push("Tier AI review cannot contain human review or second review.");
  if (regulated && (tier === "auto" || tier === "ai_review")) out.push("Regulated organisations cannot use the Auto or AI review tier.");
  for (const s of steps) {
    const thr = s.params?.threshold;
    if (s.kind === "qe" && thr !== undefined && thr !== null && !(thr >= 0 && thr <= 100)) out.push("QE threshold must be between 0 and 100.");
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
