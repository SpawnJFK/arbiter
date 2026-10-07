"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { TIER_BLURB, TIER_LABEL } from "@/lib/format";
import { TIERS, type NoReviewerPolicy, type Org, type OrgPatch } from "@/lib/types";

const POLICIES: { value: NoReviewerPolicy; title: string; body: string }[] = [
  {
    value: "wait",
    title: "Wait for a qualified reviewer",
    body: "The job pauses until a reviewer for the pair and domain is free. Slowest, but you always get the human review you paid for.",
  },
  {
    value: "ai_fallback",
    title: "Fall back to AI review, disclosed",
    body: "The AI editor and senate handle the segments instead. Every affected segment is marked in the evidence pack and on the invoice, and pricing follows the path actually taken.",
  },
  {
    value: "partial",
    title: "Deliver what is approved, hold the rest",
    body: "Approved segments are delivered on time; segments still waiting for a human are held and delivered when reviewed.",
  },
];

const VERTICALS = ["", "medical_devices", "pharma", "legal", "financial", "public_sector", "other"];

export function PolicyForm({ org, canEdit }: { org: Org; canEdit: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [v, setV] = useState<OrgPatch>({
    name: org.name,
    default_tier: org.default_tier,
    no_reviewer_policy: org.no_reviewer_policy,
    ai_subprocessors_opt_in: org.ai_subprocessors_opt_in,
    regulated: org.regulated,
    vertical: org.vertical ?? "",
    data_retention_days: org.data_retention_days,
  });
  const [busy, setBusy] = useState(false);
  const regulatedBlocks = (t: string) => Boolean(v.regulated) && (t === "auto" || t === "ai_review");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.updateOrg({ ...v, vertical: v.vertical || null });
      toast.success("Policies saved");
      router.refresh();
    } catch (err) {
      toast.error("Could not save", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      {!canEdit && <Callout tone="info">Only project managers can change organisation policies. You can view them here.</Callout>}
      <fieldset disabled={!canEdit} className="space-y-4">
        <Card>
          <CardHeader title="Organisation" />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label="Name">{(id) => <Input id={id} value={v.name ?? ""} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
            <Field label="Plan">{(id) => <Input id={id} value={org.plan} readOnly disabled />}</Field>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Default tier" description="Preselected on new quotes. You can still choose per project." />
          <CardBody className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {TIERS.map((t) => {
              const blocked = regulatedBlocks(t);
              return (
                <label
                  key={t}
                  className={cn(
                    "flex cursor-pointer flex-col rounded-md border p-3 text-[13px]",
                    v.default_tier === t ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover",
                    blocked && "cursor-not-allowed opacity-50",
                  )}
                >
                  <span className="flex items-center gap-2 font-medium">
                    <input
                      type="radio"
                      name="default_tier"
                      className="accent-[var(--accent)]"
                      checked={v.default_tier === t}
                      disabled={blocked}
                      onChange={() => setV({ ...v, default_tier: t })}
                    />
                    {TIER_LABEL[t]}
                  </span>
                  <span className="mt-1 text-muted">{blocked ? "Not allowed for regulated organisations." : TIER_BLURB[t]}</span>
                </label>
              );
            })}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="When no reviewer is available"
            description="Applies to Hybrid and Full tiers when a segment needs a human and no qualified reviewer can take it in time."
          />
          <CardBody className="space-y-3">
            <Callout tone="info">
              We never silently substitute AI for a paid human review. Whatever you choose here is recorded per segment in the
              evidence pack, and any fallback is shown on the invoice.
            </Callout>
            <div className="grid gap-2 lg:grid-cols-3">
              {POLICIES.map((p) => (
                <label
                  key={p.value}
                  className={cn(
                    "flex cursor-pointer gap-2.5 rounded-md border p-3 text-[13px]",
                    v.no_reviewer_policy === p.value ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover",
                  )}
                >
                  <input
                    type="radio"
                    name="no_reviewer_policy"
                    className="mt-0.5 accent-[var(--accent)]"
                    checked={v.no_reviewer_policy === p.value}
                    onChange={() => setV({ ...v, no_reviewer_policy: p.value })}
                  />
                  <span>
                    <span className="font-medium">{p.title}</span>
                    <span className="mt-1 block leading-relaxed text-muted">{p.body}</span>
                  </span>
                </label>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Data and compliance" />
          <CardBody className="space-y-5">
            <Checkbox
              checked={Boolean(v.ai_subprocessors_opt_in)}
              onChange={(e) => setV({ ...v, ai_subprocessors_opt_in: e.target.checked })}
              label="Allow third-party AI subprocessors"
              hint="Off: only engines covered by your data processing agreement are used, which can reduce engine choice and auto-approval. On: additional AI providers may process your content under their API terms."
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-3">
                <Checkbox
                  checked={Boolean(v.regulated)}
                  onChange={(e) => {
                    const regulated = e.target.checked;
                    const dt = regulated && (v.default_tier === "auto" || v.default_tier === "ai_review") ? "hybrid" : v.default_tier;
                    setV({ ...v, regulated, default_tier: dt });
                  }}
                  label="Regulated organisation"
                  hint="Machine-only tiers (Auto, AI review) are never offered; every shipped segment gets a human decision."
                />
                <Field label="Vertical">
                  {(id) => (
                    <Select id={id} value={v.vertical ?? ""} onChange={(e) => setV({ ...v, vertical: e.target.value })}>
                      {VERTICALS.map((x) => (
                        <option key={x} value={x}>
                          {x ? x.replace(/_/g, " ") : "Not set"}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              </div>
              <Field label="Data retention" hint="How long job data (files, segments, evidence) is kept before deletion.">
                {(id, d) => (
                  <div className="flex items-center gap-2">
                    <Input
                      id={id}
                      aria-describedby={d}
                      type="number"
                      min={1}
                      max={3650}
                      className="w-28"
                      value={v.data_retention_days ?? 365}
                      onChange={(e) => setV({ ...v, data_retention_days: Number(e.target.value) })}
                    />
                    <span className="text-[13px] text-muted">days</span>
                  </div>
                )}
              </Field>
            </div>
          </CardBody>
        </Card>
      </fieldset>
      {canEdit && (
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={busy}>
            Save policies
          </Button>
        </div>
      )}
    </form>
  );
}
