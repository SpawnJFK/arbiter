"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { TIERS, type NoReviewerPolicy, type Org, type OrgPatch } from "@/lib/types";

const POLICIES: { value: NoReviewerPolicy; title: string; body: string }[] = [
  {
    value: "wait",
    title: k("app.settings.policyForm.waitForAQualifiedReviewer"),
    body: k("app.settings.policyForm.theJobPausesUntilA"),
  },
  {
    value: "ai_fallback",
    title: k("app.settings.policyForm.fallBackToAiReview"),
    body: k("app.settings.policyForm.theAiEditorAndSenate"),
  },
  {
    value: "partial",
    title: k("app.settings.policyForm.deliverWhatIsApprovedHold"),
    body: k("app.settings.policyForm.approvedSegmentsAreDeliveredOn"),
  },
];

const VERTICALS = ["", "medical_devices", "pharma", "legal", "financial", "public_sector", "other"];

export function PolicyForm({ org, canEdit }: { org: Org; canEdit: boolean }) {
  const { t } = useI18n();
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
  const regulatedBlocks = (item: string) => Boolean(v.regulated) && (item === "auto" || item === "ai_review");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.updateOrg({ ...v, vertical: v.vertical || null });
      toast.success(t("app.settings.policyForm.policiesSaved"));
      router.refresh();
    } catch (err) {
      toast.error(t("app.settings.policyForm.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      {!canEdit && <Callout tone="info">{t("app.settings.policyForm.onlyProjectManagersCanChange")}</Callout>}
      <fieldset disabled={!canEdit} className="space-y-4">
        <Card>
          <CardHeader title={t("app.settings.policyForm.organisation")} />
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <Field label={t("app.settings.policyForm.name")}>{(id) => <Input id={id} value={v.name ?? ""} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
            <Field label={t("app.settings.policyForm.plan")}>{(id) => <Input id={id} value={org.plan} readOnly disabled />}</Field>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("app.settings.policyForm.defaultTier")} description={t("app.settings.policyForm.preselectedOnNewQuotesYou")} />
          <CardBody className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {TIERS.map((tier) => {
              const blocked = regulatedBlocks(tier);
              return (
                <label
                  key={tier}
                  className={cn(
                    "flex cursor-pointer flex-col rounded-md border p-3 text-[13px]",
                    v.default_tier === tier ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover",
                    blocked && "cursor-not-allowed opacity-50",
                  )}
                >
                  <span className="flex items-center gap-2 font-medium">
                    <input
                      type="radio"
                      name="default_tier"
                      className="accent-[var(--accent)]"
                      checked={v.default_tier === tier}
                      disabled={blocked}
                      onChange={() => setV({ ...v, default_tier: tier })}
                    />
                    {t(`tier.${tier}.label`)}
                  </span>
                  <span className="mt-1 text-muted">{blocked ? t("app.settings.policyForm.notAllowedForRegulatedOrganisations") : t(`tier.${tier}.blurb`)}</span>
                </label>
              );
            })}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={t("app.settings.policyForm.whenNoReviewerIsAvailable")}
            description={t("app.settings.policyForm.appliesToHybridAndFull")}
          />
          <CardBody className="space-y-3">
            {v.regulated && (
              <Callout tone="warn">{t("app.settings.policyForm.regulatedOrganisationsAlwaysWaitFor")}</Callout>
            )}
            <Callout tone="info">
              {t("app.settings.policyForm.weNeverSilentlySubstituteAi")}
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
                    disabled={Boolean(v.regulated) && p.value !== "wait"}
                    onChange={() => setV({ ...v, no_reviewer_policy: p.value })}
                  />
                  <span>
                    <span className="font-medium">{t(p.title)}</span>
                    <span className="mt-1 block leading-relaxed text-muted">{t(p.body)}</span>
                  </span>
                </label>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("app.settings.policyForm.dataAndCompliance")} />
          <CardBody className="space-y-5">
            <Checkbox
              checked={Boolean(v.ai_subprocessors_opt_in)}
              onChange={(e) => setV({ ...v, ai_subprocessors_opt_in: e.target.checked })}
              label={t("app.settings.policyForm.allowThirdPartyAiSubprocessors")}
              hint={t("app.settings.policyForm.offOnlyEnginesCoveredBy")}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-3">
                <Checkbox
                  checked={Boolean(v.regulated)}
                  onChange={(e) => {
                    const regulated = e.target.checked;
                    const dt = regulated && (v.default_tier === "auto" || v.default_tier === "ai_review") ? "hybrid" : v.default_tier;
                    // Regulated organisations must wait for a human (routes/auth.py PATCH /org).
                    setV({ ...v, regulated, default_tier: dt, no_reviewer_policy: regulated ? "wait" : v.no_reviewer_policy });
                  }}
                  label={t("app.settings.policyForm.regulatedOrganisation")}
                  hint={t("app.settings.policyForm.machineOnlyTiersAutoAi")}
                />
                <Field label={t("app.settings.policyForm.vertical")}>
                  {(id) => (
                    <Select id={id} value={v.vertical ?? ""} onChange={(e) => setV({ ...v, vertical: e.target.value })}>
                      {VERTICALS.map((x) => (
                        <option key={x} value={x}>
                          {x ? x.replace(/_/g, " ") : t("app.settings.policyForm.notSet")}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              </div>
              <Field label={t("app.settings.policyForm.dataRetention")} hint={t("app.settings.policyForm.howLongJobDataFiles")}>
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
                    <span className="text-[13px] text-muted">{t("app.settings.policyForm.days")}</span>
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
            {t("app.settings.policyForm.savePolicies")}
          </Button>
        </div>
      )}
    </form>
  );
}
