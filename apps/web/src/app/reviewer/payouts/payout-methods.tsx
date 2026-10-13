"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { PayoutAccountView, PayoutMethodsView, RailMethod } from "@/lib/types";

const METHOD_TEXT: Record<RailMethod, { name: string; help: string }> = {
  payoneer: { name: k("reviewer.payouts.payoneer"), help: k("reviewer.payouts.payoneerHelp") },
  paypal: { name: k("reviewer.payouts.paypal"), help: k("reviewer.payouts.paypalHelp") },
  sepa: { name: k("reviewer.payouts.sepa"), help: k("reviewer.payouts.sepaHelp") },
  wise: { name: k("reviewer.payouts.wise"), help: k("reviewer.payouts.wiseHelp") },
};

const FIELD_TEXT: Record<string, { label: string; placeholder: string; type?: string }> = {
  email: { label: k("reviewer.payouts.field.email"), placeholder: "you@example.com", type: "email" },
  iban: { label: k("reviewer.payouts.field.iban"), placeholder: "DE89 3704 0044 0532 0130 00" },
  bic: { label: k("reviewer.payouts.field.bic"), placeholder: "COBADEFFXXX" },
  account_holder: { label: k("reviewer.payouts.field.accountHolder"), placeholder: "" },
};

function MethodCard({ item }: { item: PayoutAccountView }) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [details, setDetails] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"save" | "refresh" | null>(null);
  const text = METHOD_TEXT[item.method];

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy("save");
    try {
      const clean = Object.fromEntries(Object.entries(details).map(([key, v]) => [key, v.trim()]).filter(([, v]) => v));
      const res = await api.setupPayoutAccount(item.method, clean);
      if (res.onboarding_url) {
        window.location.assign(res.onboarding_url);
        return;
      }
      toast.success(t("reviewer.payouts.saved"), t(text.name));
      router.refresh();
    } catch (err) {
      toast.error(t("reviewer.payouts.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function refresh() {
    setBusy("refresh");
    try {
      const res = await api.refreshPayoutAccount(item.method);
      toast.success(t("reviewer.payouts.statusNow", { status: t.enumLabel(res.status) }));
      router.refresh();
    } catch (err) {
      toast.error(t("reviewer.payouts.couldNotRefresh"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className={item.selected ? "border-accent ring-1 ring-accent/30" : undefined}>
      <CardHeader
        title={t(text.name)}
        description={t(text.help)}
        actions={
          <>
            {item.selected && <Badge tone="accent">{t("reviewer.payouts.inUse")}</Badge>}
            {item.status !== "not_set_up" && <StatusBadge status={item.status} />}
          </>
        }
      />
      <CardBody className="space-y-3">
        <p className="text-[12.5px] text-muted">{t("reviewer.payouts.minimum", { amount: f.money(item.minimum_payout) })}</p>
        {!item.available ? (
          <Callout tone="info">{t("reviewer.payouts.notAvailable")}</Callout>
        ) : (
          <form onSubmit={save} className="space-y-3">
            {Object.keys(item.details).length > 0 && (
              <p className="text-[12.5px] text-muted">
                {t("reviewer.payouts.onFile", { details: Object.values(item.details).filter(Boolean).join(", ") })}
              </p>
            )}
            {item.fields.map((field) => {
              const ft = FIELD_TEXT[field] ?? { label: field, placeholder: "" };
              return (
                <Field key={field} label={t(ft.label)}>
                  {(id) => (
                    <Input
                      id={id}
                      type={ft.type ?? "text"}
                      placeholder={ft.placeholder}
                      required={field !== "bic" && !(item.method === "wise" && (field === "iban" || field === "email"))}
                      value={details[field] ?? ""}
                      onChange={(e) => setDetails({ ...details, [field]: e.target.value })}
                    />
                  )}
                </Field>
              );
            })}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="primary" size="sm" loading={busy === "save"}>
                {item.onboarding_required ? t("reviewer.payouts.startOnboarding") : t("reviewer.payouts.useMethod")}
              </Button>
              {item.onboarding_url && (
                <AnchorButton size="sm" href={item.onboarding_url}>
                  {t("reviewer.payouts.continueOnboarding")}
                </AnchorButton>
              )}
              {item.onboarding_required && item.status !== "not_set_up" && (
                <Button size="sm" variant="ghost" loading={busy === "refresh"} onClick={refresh}>
                  {t("reviewer.payouts.checkStatus")}
                </Button>
              )}
            </div>
          </form>
        )}
      </CardBody>
    </Card>
  );
}

export function PayoutMethods({ view }: { view: PayoutMethodsView }) {
  const { f, t } = useI18n();
  return (
    <div className="space-y-4">
      <Callout tone="info">
        {view.selected
          ? t("reviewer.payouts.selectedNote", { method: t(METHOD_TEXT[view.selected].name), threshold: f.money(view.effective_threshold) })
          : t("reviewer.payouts.noneSelected")}
      </Callout>
      <div className="grid gap-4 lg:grid-cols-2">
        {view.items.map((item) => (
          <MethodCard key={item.method} item={item} />
        ))}
      </div>
    </div>
  );
}
