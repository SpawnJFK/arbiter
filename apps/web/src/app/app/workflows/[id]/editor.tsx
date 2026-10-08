"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Icons } from "@/components/icons";
import { WorkflowPipeline } from "@/components/workflow-pipeline";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { CONTENT_TYPES, contentTypeLabel } from "@/lib/langs";
import { STEP_KINDS, TIERS, type StepKind, type Tier, type Workflow, type WorkflowStep } from "@/lib/types";
import { cleanSteps, STEP_META, validateWorkflow } from "@/lib/workflow";

type MinLevel = "reviewer" | "senior" | "domain_expert";

export function WorkflowEditor({ workflow, template, regulated }: { workflow: Workflow | null; template: Workflow | null; regulated: boolean }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const base = workflow ?? template;
  const readOnly = Boolean(workflow?.preset);
  const [name, setName] = useState(workflow?.name ?? (template ? `${template.name} (copy)` : ""));
  const [description, setDescription] = useState(base?.description ?? "");
  const [contentType, setContentType] = useState(base?.content_type ?? "");
  const [tier, setTier] = useState<Tier>(base?.tier ?? "hybrid");
  const [isDefault, setIsDefault] = useState(workflow?.is_default ?? false);
  const [steps, setSteps] = useState<WorkflowStep[]>(
    base?.steps.map((s) => ({ kind: s.kind, params: { ...(s.params ?? {}) } })) ?? [
      { kind: "tm", params: {} },
      { kind: "mt", params: {} },
      { kind: "qe", params: {} },
      { kind: "senate", params: {} },
      { kind: "human_review", params: {} },
      { kind: "delivery", params: {} },
    ],
  );
  const [adding, setAdding] = useState<StepKind | "">("");
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const problems = useMemo(() => validateWorkflow(steps, tier, regulated, t), [steps, tier, regulated, t]);
  const available = STEP_KINDS.filter((k) => !steps.some((s) => s.kind === k));

  const update = (i: number, patch: Partial<WorkflowStep["params"]>) => setSteps(steps.map((s, j) => (j === i ? { ...s, params: { ...s.params, ...patch } } : s)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= steps.length) return;
    const next = [...steps];
    [next[i], next[j]] = [next[j], next[i]];
    setSteps(next);
  };
  function addStep(kind: StepKind) {
    // Insert before delivery (which must stay last) unless adding delivery itself.
    const at = kind === "delivery" ? steps.length : Math.max(0, steps.findIndex((s) => s.kind === "delivery"));
    const next = [...steps];
    next.splice(steps.some((s) => s.kind === "delivery") && kind !== "delivery" ? at : steps.length, 0, { kind, params: {} });
    setSteps(next);
    setAdding("");
  }

  async function save() {
    setBusy(true);
    setServerError(null);
    const body = { name: name.trim(), description, content_type: contentType || null, tier, steps: cleanSteps(steps), is_default: isDefault };
    try {
      if (workflow) {
        await api.updateWorkflow(workflow.id, body);
        toast.success(t("app.workflows.detail.editor.workflowSaved"), t("app.workflows.detail.editor.runningJobsKeepTheVersion"));
        router.refresh();
      } else {
        const w = await api.createWorkflow(body);
        toast.success(t("app.workflows.detail.editor.workflowCreated"));
        router.push(`/app/workflows/${w.id}`);
      }
    } catch (e) {
      setServerError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!workflow) return;
    try {
      await api.archiveWorkflow(workflow.id);
      toast.success(t("app.workflows.detail.editor.workflowArchived"));
      router.push("/app/workflows");
    } catch (e) {
      toast.error(t("app.workflows.detail.editor.couldNotArchive"), errorMessage(e));
    }
  }

  return (
    <div className="space-y-4">
      {readOnly && (
        <Callout tone="info" title={t("app.workflows.detail.editor.builtInPreset")}>
          {t("app.workflows.detail.editor.presetsCannotBeEdited")}{" "}
          <Link href={`/app/workflows/new?from=${workflow!.id}`} className="font-medium underline">
            {t("app.workflows.detail.editor.makeACopy")}
          </Link>{" "}{t("app.workflows.detail.editor.toChangeIt")}
        </Callout>
      )}
      <Card className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">{t("app.workflows.detail.editor.pipeline")}</h2>
          <span className={cn("text-[12.5px] font-medium", problems.length ? "text-danger" : "text-ok")}>{problems.length ? t("app.workflows.detail.editor.problems", { count: problems.length }) : t("app.workflows.detail.editor.valid")}</span>
        </div>
        <WorkflowPipeline steps={steps} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader title={t("app.workflows.detail.editor.steps")} description={t("app.workflows.detail.editor.orderMattersTranslationThenQe")} />
          <fieldset disabled={readOnly}>
            <ol className="divide-y divide-border">
              {steps.map((s, i) => {
                const meta = STEP_META[s.kind];
                return (
                  <li key={`${s.kind}-${i}`} className="flex flex-wrap items-start gap-3 px-4 py-3">
                    <span className="tabular mt-1.5 w-5 text-[12px] text-faint">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] font-medium">{t(meta.label)}</div>
                      <div className="text-[12.5px] text-muted">{t(meta.help)}</div>
                      {s.kind === "mt" && (
                        <div className="mt-2 max-w-xs">
                          <Field label={t("app.workflows.detail.editor.preferredEngineOptional")}>
                            {(id) => <Input id={id} value={s.params?.engine ?? ""} onChange={(e) => update(i, { engine: e.target.value })} placeholder={t("app.workflows.detail.editor.leaveEmptyToLetRouting")} />}
                          </Field>
                        </div>
                      )}
                      {s.kind === "qe" && (
                        <div className="mt-2 max-w-xs">
                          <Field label={t("app.workflows.detail.editor.thresholdOverride0To100")}>
                            {(id) => (
                              <Input
                                id={id}
                                type="number"
                                min={0}
                                max={100}
                                step="0.5"
                                value={s.params?.threshold ?? ""}
                                onChange={(e) => update(i, { threshold: e.target.value === "" ? undefined : Number(e.target.value) })}
                                placeholder={t("app.workflows.detail.editor.calibratedPerContentType")}
                              />
                            )}
                          </Field>
                        </div>
                      )}
                      {(s.kind === "human_review" || s.kind === "second_review") && (
                        <div className="mt-2 max-w-xs">
                          <Field label={t("app.workflows.detail.editor.minimumReviewerLevel")}>
                            {(id) => (
                              <Select id={id} value={s.params?.min_level ?? ""} onChange={(e) => update(i, { min_level: (e.target.value || undefined) as MinLevel | undefined })}>
                                <option value="">{s.kind === "second_review" ? t("app.workflows.detail.editor.seniorDefault") : t("app.workflows.detail.editor.anyActiveReviewer")}</option>
                                <option value="reviewer">{t("app.workflows.detail.editor.reviewer")}</option>
                                <option value="senior">{t("app.workflows.detail.editor.senior")}</option>
                                <option value="domain_expert">{t("app.workflows.detail.editor.domainExpert")}</option>
                              </Select>
                            )}
                          </Field>
                        </div>
                      )}
                    </div>
                    <div className="flex gap-0.5">
                      <Button size="sm" variant="ghost" aria-label={t("app.workflows.detail.editor.moveUp", { label: t(meta.label) })} disabled={i === 0} onClick={() => move(i, -1)}>
                        <Icons.up className="size-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={t("app.workflows.detail.editor.moveDown", { label: t(meta.label) })} disabled={i === steps.length - 1} onClick={() => move(i, 1)}>
                        <Icons.down className="size-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={t("app.workflows.detail.editor.remove", { label: t(meta.label) })} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                        <Icons.trash className="size-3.5" />
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ol>
            {available.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
                <Select aria-label={t("app.workflows.detail.editor.stepToAdd")} value={adding} onChange={(e) => setAdding(e.target.value as StepKind)} className="w-60">
                  <option value="">{t("app.workflows.detail.editor.addAStep")}</option>
                  {available.map((k) => (
                    <option key={k} value={k}>
                      {t(STEP_META[k].label)}
                    </option>
                  ))}
                </Select>
                <Button onClick={() => adding && addStep(adding)} disabled={!adding}>
                  <Icons.plus className="size-3.5" /> {t("app.workflows.detail.editor.add")}
                </Button>
              </div>
            )}
          </fieldset>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardBody className="space-y-4">
              <fieldset disabled={readOnly} className="space-y-4">
                <Field label={t("app.workflows.detail.editor.name")}>{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
                <Field label={t("app.workflows.detail.editor.tier")} hint={t(`tier.${tier}.blurb`)}>
                  {(id, d) => (
                    <Select id={id} aria-describedby={d} value={tier} onChange={(e) => setTier(e.target.value as Tier)}>
                      {TIERS.map((tier) => (
                        <option key={tier} value={tier} disabled={regulated && (tier === "auto" || tier === "ai_review")}>
                          {t(`tier.${tier}.label`)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label={t("app.workflows.detail.editor.contentTypeOptional")}>
                  {(id) => (
                    <Select id={id} value={contentType} onChange={(e) => setContentType(e.target.value)}>
                      <option value="">{t("app.workflows.detail.editor.any")}</option>
                      {contentType && !CONTENT_TYPES.some((c) => c.value === contentType) && <option value={contentType}>{contentType}</option>}
                      {CONTENT_TYPES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {contentTypeLabel(t, c.value)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label={t("app.workflows.detail.editor.description")}>{(id) => <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} className="min-h-16" />}</Field>
                <Checkbox label={t("app.workflows.detail.editor.orgDefault")} hint={t("app.workflows.detail.editor.projectsWithoutAnAccountWorkflow")} checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
              </fieldset>
            </CardBody>
          </Card>
          <Card className="p-4" aria-live="polite">
            <h2 className="mb-2 text-sm font-semibold">{t("app.workflows.detail.editor.validation")}</h2>
            {problems.length === 0 ? (
              <p className="text-[13px] text-ok">{t("app.workflows.detail.editor.allRulesPass")}</p>
            ) : (
              <ul className="space-y-1.5 text-[13px] text-danger">
                {problems.map((p) => (
                  <li key={p} className="flex gap-1.5">
                    <Icons.alert className="mt-0.5 size-3.5 shrink-0" />
                    {p}
                  </li>
                ))}
              </ul>
            )}
            {serverError && <p className="mt-2 text-[13px] text-danger">{t("app.workflows.detail.editor.server", { serverError: serverError })}</p>}
          </Card>
          {!readOnly && (
            <div className="flex justify-between gap-2">
              {workflow ? (
                <Button variant="outline-danger" onClick={archive}>
                  {t("app.workflows.detail.editor.archive")}
                </Button>
              ) : (
                <span />
              )}
              <Button variant="primary" onClick={save} loading={busy} disabled={problems.length > 0 || !name.trim()}>
                {workflow ? t("app.workflows.detail.editor.saveWorkflow") : t("app.workflows.detail.editor.createWorkflow")}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
