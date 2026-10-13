"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage, newIdempotencyKey } from "@/lib/api";
import { MODULE_KEYS, MODULE_LABEL } from "@/lib/billing";
import type { AdminOverride, BillingOverview, ModuleKey, OrgWithUsage, Plan } from "@/lib/types";

export function OrgOverride({
  orgs,
  plans,
  overview,
  orgId,
}: {
  orgs: OrgWithUsage[];
  plans: Plan[];
  overview: BillingOverview | null;
  orgId: string | null;
}) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const sub = overview?.subscription ?? null;
  const [plan, setPlan] = useState("");
  const [seats, setSeats] = useState("");
  const [add, setAdd] = useState<ModuleKey[]>(overview?.overrides?.add ?? []);
  const [remove, setRemove] = useState<ModuleKey[]>(overview?.overrides?.remove ?? []);
  const [fee, setFee] = useState(overview?.platform_fee_percent ?? "");
  const [terms, setTerms] = useState(String(overview?.payment_terms_days ?? 14));
  const [po, setPo] = useState(overview?.po_number ?? "");
  const [provider, setProvider] = useState<string>(overview?.provider_override ?? "");
  const [note, setNote] = useState("");
  const [grant, setGrant] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key);
    try {
      await fn();
      toast.success(ok);
      router.refresh();
    } catch (err) {
      toast.error(t("admin.billing.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    if (!orgId) return;
    const body: AdminOverride = {
      modules_add: add,
      modules_remove: remove,
      payment_terms_days: Number(terms) || 0,
      po_number: po,
      provider: (provider || "") as AdminOverride["provider"],
      note,
    };
    if (plan) body.plan = plan;
    if (seats) body.seats = Number(seats);
    if (fee) body.platform_fee_percent = fee;
    void run("save", () => api.overrideOrgBilling(orgId, body), t("admin.billing.overrideSaved"));
  }

  const toggle = (list: ModuleKey[], set: (v: ModuleKey[]) => void, m: ModuleKey, on: boolean) =>
    set(on ? [...list, m] : list.filter((x) => x !== m));

  return (
    <Card>
      <CardHeader
        title={t("admin.billing.orgTitle")}
        description={t("admin.billing.orgHelp")}
        actions={
          <Select
            aria-label={t("admin.billing.organisation")}
            className="w-64"
            value={orgId ?? ""}
            onChange={(e) => router.push(e.target.value ? `/admin/billing?org=${encodeURIComponent(e.target.value)}` : "/admin/billing")}
          >
            <option value="">{t("admin.billing.pickOrg")}</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </Select>
        }
      />
      {!overview || !orgId ? (
        <EmptyState title={t("admin.billing.noOrgSelected")} description={t("admin.billing.noOrgSelectedHelp")} />
      ) : (
        <CardBody className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
            {sub ? (
              <>
                <span className="font-semibold">{plans.find((p) => p.key === sub.plan)?.name ?? sub.plan}</span>
                <StatusBadge status={sub.status} />
                <Badge>{t.enumLabel(sub.provider)}</Badge>
                <span className="text-muted">
                  {t("admin.billing.seatsOf", { used: overview.seats_used, total: sub.seats })} · {t("admin.billing.until")} <Time iso={sub.current_period_end} />
                </span>
              </>
            ) : (
              <span className="text-muted">{t("admin.billing.noSubscription")}</span>
            )}
            <span className="text-muted">· {t("admin.billing.creditsBalance", { amount: f.money(overview.credits_balance) })}</span>
          </div>
          <div className="flex flex-wrap gap-1" aria-label={t("admin.billing.modules")}>
            {overview.modules.map((m) => (
              <Badge key={m} tone="ok">
                {t(MODULE_LABEL[m])}
              </Badge>
            ))}
          </div>

          <form onSubmit={save} className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={t("admin.billing.setPlan")} hint={t("admin.billing.setPlanHint")}>
                {(id, h) => (
                  <Select id={id} aria-describedby={h} value={plan} onChange={(e) => setPlan(e.target.value)}>
                    <option value="">{t("admin.billing.keepPlan")}</option>
                    {plans.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={t("admin.billing.seats")}>
                {(id) => <Input id={id} inputMode="numeric" value={seats} placeholder={sub ? String(sub.seats) : ""} onChange={(e) => setSeats(e.target.value)} />}
              </Field>
              <Field label={t("admin.billing.fee")} hint={t("admin.billing.feeHint")}>
                {(id, h) => <Input id={id} aria-describedby={h} inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} />}
              </Field>
              <Field label={t("admin.billing.provider")} hint={t("admin.billing.providerHint")}>
                {(id, h) => (
                  <Select id={id} aria-describedby={h} value={provider} onChange={(e) => setProvider(e.target.value)}>
                    <option value="">{t("admin.billing.providerDefault")}</option>
                    <option value="paddle">{t.enumLabel("paddle")}</option>
                    <option value="manual">{t.enumLabel("manual")}</option>
                    <option value="stripe">{t.enumLabel("stripe")}</option>
                  </Select>
                )}
              </Field>
              <Field label={t("admin.billing.terms")}>
                {(id) => <Input id={id} inputMode="numeric" value={terms} onChange={(e) => setTerms(e.target.value)} />}
              </Field>
              <Field label={t("admin.billing.po")}>
                {(id) => <Input id={id} value={po} maxLength={60} onChange={(e) => setPo(e.target.value)} />}
              </Field>
              <Field label={t("admin.billing.note")} className="sm:col-span-2">
                {(id) => <Input id={id} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}
              </Field>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <fieldset>
                <legend className="mb-1.5 text-[13px] font-medium">{t("admin.billing.alwaysInclude")}</legend>
                <div className="flex flex-wrap gap-x-4 gap-y-2">
                  {MODULE_KEYS.map((m) => (
                    <Checkbox key={m} label={t(MODULE_LABEL[m])} checked={add.includes(m)} onChange={(e) => toggle(add, setAdd, m, e.target.checked)} />
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend className="mb-1.5 text-[13px] font-medium">{t("admin.billing.alwaysExclude")}</legend>
                <div className="flex flex-wrap gap-x-4 gap-y-2">
                  {MODULE_KEYS.map((m) => (
                    <Checkbox key={m} label={t(MODULE_LABEL[m])} checked={remove.includes(m)} onChange={(e) => toggle(remove, setRemove, m, e.target.checked)} />
                  ))}
                </div>
              </fieldset>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="primary" size="sm" loading={busy === "save"}>
                {t("admin.billing.saveOverride")}
              </Button>
              {sub && (sub.provider === "admin" || sub.provider === "manual") && (
                <Button
                  size="sm"
                  variant="outline-danger"
                  loading={busy === "cancel"}
                  onClick={() => run("cancel", () => api.overrideOrgBilling(orgId, { status: "canceled" }), t("admin.billing.canceled"))}
                >
                  {t("admin.billing.cancelSubscription")}
                </Button>
              )}
            </div>
          </form>

          <div className="flex flex-wrap items-end gap-2 border-t border-border pt-4">
            <Field label={t("admin.billing.grantCredits")} hint={t("admin.billing.grantHint")}>
              {(id, h) => <Input id={id} aria-describedby={h} inputMode="decimal" className="w-40" value={grant} onChange={(e) => setGrant(e.target.value)} />}
            </Field>
            <Button
              size="sm"
              disabled={!grant}
              loading={busy === "grant"}
              onClick={() =>
                run(
                  "grant",
                  async () => {
                    await api.grantCredits(orgId, { amount: grant, note: note || "admin grant", idempotency_key: newIdempotencyKey() });
                    setGrant("");
                  },
                  t("admin.billing.granted"),
                )
              }
            >
              {t("admin.billing.grant")}
            </Button>
          </div>
        </CardBody>
      )}
    </Card>
  );
}
