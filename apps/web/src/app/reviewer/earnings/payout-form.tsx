"use client";

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
    label: "SEPA bank transfer",
    fields: [
      { key: "iban", label: "IBAN", placeholder: "DE89 3704 0044 0532 0130 00" },
      { key: "bic", label: "BIC", placeholder: "COBADEFFXXX" },
    ],
  },
  { value: "wise", label: "Wise", fields: [{ key: "email", label: "Wise account email", placeholder: "you@example.com" }] },
  { value: "paypal", label: "PayPal", fields: [{ key: "email", label: "PayPal email", placeholder: "you@example.com" }] },
];

export function PayoutForm({ complete, country: initialCountry }: { complete: boolean; country: string }) {
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
      const payout_details = Object.fromEntries(method.fields.map((f) => [f.key, (details[f.key] ?? "").trim()]));
      const res = await api.updateReviewerMe({ ...v, country: v.country.toUpperCase(), payout_method: methodValue, payout_details });
      toast.success("Payout details saved", res.tax_info_complete ? "You are eligible for the next payout run." : "Some required details are still missing.");
      router.refresh();
    } catch (err) {
      toast.error("Could not save", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="payout" className="self-start">
      <CardHeader
        title="Tax and payout details"
        description={complete ? "On file. Submit the form again to change them." : "Required before your first payout."}
      />
      <CardBody>
        <Callout tone="info" className="mb-4">
          Platforms that pay service providers must collect and report these details to tax authorities (for example under the EU
          DAC7 rules). We only use them for payouts and that reporting. Existing values are never shown back here.
        </Callout>
        <form onSubmit={save} className="space-y-4">
          <Field label="Legal name" hint="As on your ID or business registration.">
            {(id, d) => <Input id={id} aria-describedby={d} required autoComplete="name" value={v.legal_name} onChange={(e) => setV({ ...v, legal_name: e.target.value })} />}
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Tax ID" hint="TIN, VAT ID or equivalent." className="sm:col-span-1">
              {(id, d) => <Input id={id} aria-describedby={d} required value={v.tax_id} onChange={(e) => setV({ ...v, tax_id: e.target.value })} />}
            </Field>
            <Field label="Date of birth">
              {(id) => <Input id={id} type="date" required autoComplete="bday" value={v.date_of_birth} onChange={(e) => setV({ ...v, date_of_birth: e.target.value })} />}
            </Field>
            <Field label="Country" hint="Two letters, e.g. DE">
              {(id, d) => (
                <Input id={id} aria-describedby={d} required maxLength={2} pattern="[A-Za-z]{2}" value={v.country} onChange={(e) => setV({ ...v, country: e.target.value })} />
              )}
            </Field>
          </div>
          <Field label="Address" hint="Primary residence or registered business address.">
            {(id, d) => (
              <Textarea id={id} aria-describedby={d} required autoComplete="street-address" className="min-h-16" value={v.address} onChange={(e) => setV({ ...v, address: e.target.value })} />
            )}
          </Field>
          <Field label="Payout method">
            {(id) => (
              <Select id={id} value={methodValue} onChange={(e) => setMethodValue(e.target.value as PayoutMethod)}>
                {METHODS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            {method.fields.map((f) => (
              <Field key={`${method.value}-${f.key}`} label={f.label}>
                {(id) => <Input id={id} required placeholder={f.placeholder} value={details[f.key] ?? ""} onChange={(e) => setDetails({ ...details, [f.key]: e.target.value })} />}
              </Field>
            ))}
          </div>
          <Button type="submit" variant="primary" loading={busy}>
            Save details
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
