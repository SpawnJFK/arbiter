"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { PayoutInfo, PayoutMethod } from "@/lib/types";

const METHODS: { value: PayoutMethod; label: string; detailsLabel: string; placeholder: string }[] = [
  { value: "bank_transfer", label: "Bank transfer (IBAN)", detailsLabel: "IBAN and BIC", placeholder: "DE89 3704 0044 0532 0130 00, COBADEFFXXX" },
  { value: "wise", label: "Wise", detailsLabel: "Wise account email", placeholder: "you@example.com" },
  { value: "paypal", label: "PayPal", detailsLabel: "PayPal email", placeholder: "you@example.com" },
];

export function PayoutForm({ complete }: { complete: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [v, setV] = useState<Required<PayoutInfo>>({
    legal_name: "",
    tax_id: "",
    address: "",
    date_of_birth: "",
    payout_method: "bank_transfer",
    payout_details: "",
  });
  const [busy, setBusy] = useState(false);
  const method = METHODS.find((m) => m.value === v.payout_method) ?? METHODS[0];

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.updateReviewerMe(v);
      toast.success("Payout details saved", res.tax_info_complete ? "You are eligible for the next payout run." : undefined);
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
          Platforms that pay sellers and service providers must collect and report these details to tax authorities (for example
          under the EU DAC7 rules). We only use them for payouts and that reporting. Existing values are never shown back here.
        </Callout>
        <form onSubmit={save} className="space-y-4">
          <Field label="Legal name" hint="As on your ID or business registration.">
            {(id, d) => <Input id={id} aria-describedby={d} required autoComplete="name" value={v.legal_name} onChange={(e) => setV({ ...v, legal_name: e.target.value })} />}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Tax ID" hint="TIN, VAT ID or national equivalent.">
              {(id, d) => <Input id={id} aria-describedby={d} required value={v.tax_id} onChange={(e) => setV({ ...v, tax_id: e.target.value })} />}
            </Field>
            <Field label="Date of birth">
              {(id) => <Input id={id} type="date" required autoComplete="bday" value={v.date_of_birth} onChange={(e) => setV({ ...v, date_of_birth: e.target.value })} />}
            </Field>
          </div>
          <Field label="Address" hint="Primary residence or registered business address.">
            {(id, d) => (
              <Textarea id={id} aria-describedby={d} required autoComplete="street-address" className="min-h-16" value={v.address} onChange={(e) => setV({ ...v, address: e.target.value })} />
            )}
          </Field>
          <div className="grid gap-4 sm:grid-cols-[1fr_1.4fr]">
            <Field label="Payout method">
              {(id) => (
                <Select id={id} value={v.payout_method} onChange={(e) => setV({ ...v, payout_method: e.target.value as PayoutMethod })}>
                  {METHODS.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={method.detailsLabel}>
              {(id) => <Input id={id} required placeholder={method.placeholder} value={v.payout_details} onChange={(e) => setV({ ...v, payout_details: e.target.value })} />}
            </Field>
          </div>
          <Button type="submit" variant="primary" loading={busy}>
            Save details
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
