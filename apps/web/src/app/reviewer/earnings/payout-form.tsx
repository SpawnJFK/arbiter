"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { PayoutMethod } from "@/lib/types";

// community/profiles.py PAYOUT_METHODS; payout_details is an object.
const METHODS: { value: PayoutMethod; label: string; fields: { key: string; label: string; placeholder: string }[] }[] = [
  {
    value: "sepa",
    label: k("reviewer.earnings.payoutForm.sepaBankTransfer"),
    fields: [
      { key: "iban", label: k("reviewer.earnings.payoutForm.iban"), placeholder: "DE89 3704 0044 0532 0130 00" },
      { key: "bic", label: k("reviewer.earnings.payoutForm.bic"), placeholder: "COBADEFFXXX" },
    ],
  },
  { value: "wise", label: k("reviewer.earnings.payoutForm.wise"), fields: [{ key: "email", label: k("reviewer.earnings.payoutForm.wiseAccountEmail"), placeholder: "you@example.com" }] },
  { value: "paypal", label: k("reviewer.earnings.payoutForm.paypal"), fields: [{ key: "email", label: k("reviewer.earnings.payoutForm.paypalEmail"), placeholder: "you@example.com" }] },
];

export function PayoutForm({ complete, country: initialCountry }: { complete: boolean; country: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [v, setV] = useState({ legal_name: "", tax_id: "", address: "", date_of_birth: "", country: initialCountry });
  const [methodValue, setMethodValue] = useState<PayoutMethod>("sepa");
  const [details, setDetails] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const method = METHODS.find((m) => m.value === methodValue) ?? METHODS[0];

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const payout_details = Object.fromEntries(method.fields.map((frac) => [frac.key, (details[frac.key] ?? "").trim()]));
      const res = await api.updateReviewerMe({ ...v, country: v.country.toUpperCase(), payout_method: methodValue, payout_details });
      toast.success(t("reviewer.earnings.payoutForm.payoutDetailsSaved"), res.tax_info_complete ? t("reviewer.earnings.payoutForm.eligible") : t("reviewer.earnings.payoutForm.detailsMissing"));
      router.refresh();
    } catch (err) {
      toast.error(t("reviewer.earnings.payoutForm.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="payout" className="self-start">
      <CardHeader
        title={t("reviewer.earnings.payoutForm.taxAndPayoutDetails")}
        description={complete ? t("reviewer.earnings.payoutForm.onFileSubmitTheForm") : t("reviewer.earnings.payoutForm.requiredBeforeYourFirstPayout")}
      />
      <CardBody>
        <Callout tone="info" className="mb-4">
          {t("reviewer.earnings.payoutForm.platformsThatPayServiceProviders")}
        </Callout>
        <form onSubmit={save} className="space-y-4">
          <Field label={t("reviewer.earnings.payoutForm.legalName")} hint={t("reviewer.earnings.payoutForm.asOnYourIdOr")}>
            {(id, d) => <Input id={id} aria-describedby={d} required autoComplete="name" value={v.legal_name} onChange={(e) => setV({ ...v, legal_name: e.target.value })} />}
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t("reviewer.earnings.payoutForm.taxId")} hint={t("reviewer.earnings.payoutForm.tinVatIdOrEquivalent")} className="sm:col-span-1">
              {(id, d) => <Input id={id} aria-describedby={d} required value={v.tax_id} onChange={(e) => setV({ ...v, tax_id: e.target.value })} />}
            </Field>
            <Field label={t("reviewer.earnings.payoutForm.dateOfBirth")}>
              {(id) => <Input id={id} type="date" required autoComplete="bday" value={v.date_of_birth} onChange={(e) => setV({ ...v, date_of_birth: e.target.value })} />}
            </Field>
            <Field label={t("reviewer.earnings.payoutForm.country")} hint={t("reviewer.earnings.payoutForm.twoLettersEGDe")}>
              {(id, d) => (
                <Input id={id} aria-describedby={d} required maxLength={2} pattern="[A-Za-z]{2}" value={v.country} onChange={(e) => setV({ ...v, country: e.target.value })} />
              )}
            </Field>
          </div>
          <Field label={t("reviewer.earnings.payoutForm.address")} hint={t("reviewer.earnings.payoutForm.primaryResidenceOrRegisteredBusiness")}>
            {(id, d) => (
              <Textarea id={id} aria-describedby={d} required autoComplete="street-address" className="min-h-16" value={v.address} onChange={(e) => setV({ ...v, address: e.target.value })} />
            )}
          </Field>
          <Field label={t("reviewer.earnings.payoutForm.payoutMethod")}>
            {(id) => (
              <Select id={id} value={methodValue} onChange={(e) => setMethodValue(e.target.value as PayoutMethod)}>
                {METHODS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {t(m.label)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            {method.fields.map((frac) => (
              <Field key={`${method.value}-${frac.key}`} label={t(frac.label)}>
                {(id) => <Input id={id} required placeholder={frac.placeholder} value={details[frac.key] ?? ""} onChange={(e) => setDetails({ ...details, [frac.key]: e.target.value })} />}
              </Field>
            ))}
          </div>
          <Button type="submit" variant="primary" loading={busy}>
            {t("reviewer.earnings.payoutForm.saveDetails")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
