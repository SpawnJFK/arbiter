"use client";

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
import { TIER_BLURB, TIER_LABEL } from "@/lib/format";
import { CONTENT_TYPES } from "@/lib/langs";
import { STEP_KINDS, TIERS, type StepKind, type Tier, type Workflow, type WorkflowStep } from "@/lib/types";
import { cleanSteps, STEP_META, validateWorkflow } from "@/lib/workflow";

type MinLevel = "reviewer" | "senior" | "domain_expert";

export function WorkflowEditor({ workflow, template, regulated }: { workflow: Workflow | null; template: Workflow | null; regulated: boolean }) {
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

  const problems = useMemo(() => validateWorkflow(steps, tier, regulated), [steps, tier, regulated]);
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
        toast.success("Workflow saved", "Running jobs keep the version they started with.");
        router.refresh();
      } else {
        const w = await api.createWorkflow(body);
        toast.success("Workflow created");
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
      toast.success("Workflow archived");
      router.push("/app/workflows");
    } catch (e) {
      toast.error("Could not archive", errorMessage(e));
    }
  }

  return (
    <div className="space-y-4">
      {readOnly && (
        <Callout tone="info" title="Built-in preset">
          Presets cannot be edited.{" "}
          <Link href={`/app/workflows/new?from=${workflow!.id}`} className="font-medium underline">
            Make a copy
          </Link>{" "}
          to change it.
        </Callout>
      )}
      <Card className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Pipeline</h2>
          <span className={cn("text-[12.5px] font-medium", problems.length ? "text-danger" : "text-ok")}>{problems.length ? `${problems.length} problem${problems.length > 1 ? "s" : ""}` : "Valid"}</span>
        </div>
        <WorkflowPipeline steps={steps} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader title="Steps" description="Order matters: translation, then QE, then reviews, delivery last." />
          <fieldset disabled={readOnly}>
            <ol className="divide-y divide-border">
              {steps.map((s, i) => {
                const meta = STEP_META[s.kind];
                return (
                  <li key={`${s.kind}-${i}`} className="flex flex-wrap items-start gap-3 px-4 py-3">
                    <span className="tabular mt-1.5 w-5 text-[12px] text-faint">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] font-medium">{meta.label}</div>
                      <div className="text-[12.5px] text-muted">{meta.help}</div>
                      {s.kind === "mt" && (
                        <div className="mt-2 max-w-xs">
                          <Field label="Preferred engine (optional)">
                            {(id) => <Input id={id} value={s.params?.engine ?? ""} onChange={(e) => update(i, { engine: e.target.value })} placeholder="Leave empty to let routing decide" />}
                          </Field>
                        </div>
                      )}
                      {s.kind === "qe" && (
                        <div className="mt-2 max-w-xs">
                          <Field label="Threshold override (0 to 100, optional)">
                            {(id) => (
                              <Input
                                id={id}
                                type="number"
                                min={0}
                                max={100}
                                step="0.5"
                                value={s.params?.threshold ?? ""}
                                onChange={(e) => update(i, { threshold: e.target.value === "" ? undefined : Number(e.target.value) })}
                                placeholder="Calibrated per content type"
                              />
                            )}
                          </Field>
                        </div>
                      )}
                      {(s.kind === "human_review" || s.kind === "second_review") && (
                        <div className="mt-2 max-w-xs">
                          <Field label="Minimum reviewer level">
                            {(id) => (
                              <Select id={id} value={s.params?.min_level ?? ""} onChange={(e) => update(i, { min_level: (e.target.value || undefined) as MinLevel | undefined })}>
                                <option value="">{s.kind === "second_review" ? "Senior (default)" : "Any active reviewer"}</option>
                                <option value="reviewer">Reviewer</option>
                                <option value="senior">Senior</option>
                                <option value="domain_expert">Domain expert</option>
                              </Select>
                            )}
                          </Field>
                        </div>
                      )}
                    </div>
                    <div className="flex gap-0.5">
                      <Button size="sm" variant="ghost" aria-label={`Move ${meta.label} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                        <Icons.up className="size-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={`Move ${meta.label} down`} disabled={i === steps.length - 1} onClick={() => move(i, 1)}>
                        <Icons.down className="size-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={`Remove ${meta.label}`} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                        <Icons.trash className="size-3.5" />
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ol>
            {available.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
                <Select aria-label="Step to add" value={adding} onChange={(e) => setAdding(e.target.value as StepKind)} className="w-60">
                  <option value="">Add a step…</option>
                  {available.map((k) => (
                    <option key={k} value={k}>
                      {STEP_META[k].label}
                    </option>
                  ))}
                </Select>
                <Button onClick={() => adding && addStep(adding)} disabled={!adding}>
                  <Icons.plus className="size-3.5" /> Add
                </Button>
              </div>
            )}
          </fieldset>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardBody className="space-y-4">
              <fieldset disabled={readOnly} className="space-y-4">
                <Field label="Name">{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
                <Field label="Tier" hint={TIER_BLURB[tier]}>
                  {(id, d) => (
                    <Select id={id} aria-describedby={d} value={tier} onChange={(e) => setTier(e.target.value as Tier)}>
                      {TIERS.map((t) => (
                        <option key={t} value={t} disabled={regulated && (t === "auto" || t === "ai_review")}>
                          {TIER_LABEL[t]}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label="Content type (optional)">
                  {(id) => (
                    <Select id={id} value={contentType} onChange={(e) => setContentType(e.target.value)}>
                      <option value="">Any</option>
                      {contentType && !CONTENT_TYPES.some((c) => c.value === contentType) && <option value={contentType}>{contentType}</option>}
                      {CONTENT_TYPES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label="Description">{(id) => <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} className="min-h-16" />}</Field>
                <Checkbox label="Org default" hint="Projects without an account workflow or explicit tier use it." checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
              </fieldset>
            </CardBody>
          </Card>
          <Card className="p-4" aria-live="polite">
            <h2 className="mb-2 text-sm font-semibold">Validation</h2>
            {problems.length === 0 ? (
              <p className="text-[13px] text-ok">All rules pass.</p>
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
            {serverError && <p className="mt-2 text-[13px] text-danger">Server: {serverError}</p>}
          </Card>
          {!readOnly && (
            <div className="flex justify-between gap-2">
              {workflow ? (
                <Button variant="outline-danger" onClick={archive}>
                  Archive
                </Button>
              ) : (
                <span />
              )}
              <Button variant="primary" onClick={save} loading={busy} disabled={problems.length > 0 || !name.trim()}>
                {workflow ? "Save workflow" : "Create workflow"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
