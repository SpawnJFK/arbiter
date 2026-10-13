"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/input";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { MODULE_KEYS, MODULE_LABEL } from "@/lib/billing";
import type { ModuleKey, Plan, ProviderStatus } from "@/lib/types";

const BASE_CURRENCIES = ["EUR", "USD"];

type Draft = {
  key: string;
  name: string;
  description: string;
  modules: ModuleKey[];
  prices: Record<string, string>; // "month:EUR" -> "49.00"
  seatPrices: Record<string, string>;
  overage: Record<string, string>; // "EUR:word" -> "0.015"
  includedWords: string;
  includedAi: string;
  seats: string;
  maxSeats: string;
  custom: boolean;
  public: boolean;
  active: boolean;
  sort: string;
};

function toDraft(p: Plan | null): Draft {
  const flat = (table: Plan["prices"] | undefined) => {
    const out: Record<string, string> = {};
    for (const [iv, byCur] of Object.entries(table ?? {})) for (const [c, v] of Object.entries(byCur ?? {})) out[`${iv}:${c}`] = String(v);
    return out;
  };
  const overage: Record<string, string> = {};
  for (const [c, rates] of Object.entries(p?.overage ?? {})) for (const [u, v] of Object.entries(rates)) overage[`${c}:${u}`] = String(v);
  return {
    key: p?.key ?? "",
    name: p?.name ?? "",
    description: p?.description ?? "",
    modules: p?.modules ?? ["tms"],
    prices: flat(p?.prices),
    seatPrices: flat(p?.seat_prices),
    overage,
    includedWords: p?.included?.word ?? "",
    includedAi: p?.included?.ai_unit ?? "",
    seats: String(p?.seats_included ?? 1),
    maxSeats: p?.max_seats == null ? "" : String(p.max_seats),
    custom: p?.custom ?? false,
    public: p?.public ?? true,
    active: p?.active ?? true,
    sort: String(p?.sort ?? 100),
  };
}

function fromDraft(d: Draft) {
  const table = (flat: Record<string, string>) => {
    const out: Record<string, Record<string, string>> = {};
    for (const [key, v] of Object.entries(flat)) {
      if (!v.trim()) continue;
      const [iv, c] = key.split(":");
      (out[iv] ??= {})[c] = v.trim();
    }
    return out;
  };
  const overage: Record<string, Record<string, string>> = {};
  for (const [key, v] of Object.entries(d.overage)) {
    if (!v.trim()) continue;
    const [c, u] = key.split(":");
    (overage[c] ??= {})[u] = v.trim();
  }
  const included: Record<string, string> = {};
  if (d.includedWords.trim()) included.word = d.includedWords.trim();
  if (d.includedAi.trim()) included.ai_unit = d.includedAi.trim();
  return {
    name: d.name.trim(),
    description: d.description,
    modules: d.modules,
    prices: table(d.prices),
    seat_prices: table(d.seatPrices),
    included,
    overage,
    seats_included: Number(d.seats) || 0,
    max_seats: d.maxSeats.trim() ? Number(d.maxSeats) : null,
    custom: d.custom,
    public: d.public,
    active: d.active,
    sort: Number(d.sort) || 0,
  } as Partial<Plan>;
}

function PlanForm({ plan, onDone }: { plan: Plan | null; onDone: () => void }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [d, setD] = useState<Draft>(() => toDraft(plan));
  const [busy, setBusy] = useState(false);
  const currencies = [...new Set([...BASE_CURRENCIES, ...(plan?.currencies ?? [])])];

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (plan) await api.updatePlan(plan.key, fromDraft(d));
      else await api.createPlan({ key: d.key.trim(), name: d.name.trim(), ...fromDraft(d) });
      toast.success(t("admin.billing.planSaved"), d.name);
      onDone();
      router.refresh();
    } catch (err) {
      toast.error(t("admin.billing.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const money = (group: "prices" | "seatPrices", key: string) => (
    <Input
      inputMode="decimal"
      aria-label={key}
      placeholder="0.00"
      value={d[group][key] ?? ""}
      onChange={(e) => setD({ ...d, [group]: { ...d[group], [key]: e.target.value } })}
    />
  );

  return (
    <form onSubmit={save} className="space-y-4 border-t border-border bg-subtle/40 p-4">
      <div className="grid gap-3 md:grid-cols-3">
        {!plan && (
          <Field label={t("admin.billing.key")} hint={t("admin.billing.keyHint")}>
            {(id, h) => <Input id={id} aria-describedby={h} required pattern="[a-z0-9_-]{1,40}" value={d.key} onChange={(e) => setD({ ...d, key: e.target.value })} />}
          </Field>
        )}
        <Field label={t("admin.billing.name")}>
          {(id) => <Input id={id} required value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} />}
        </Field>
        <Field label={t("admin.billing.sort")}>
          {(id) => <Input id={id} inputMode="numeric" value={d.sort} onChange={(e) => setD({ ...d, sort: e.target.value })} />}
        </Field>
      </div>
      <Field label={t("admin.billing.descriptionField")}>
        {(id) => <Textarea id={id} className="min-h-14" value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })} />}
      </Field>
      <fieldset>
        <legend className="mb-1.5 text-[13px] font-medium">{t("admin.billing.modules")}</legend>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {MODULE_KEYS.map((m) => (
            <Checkbox
              key={m}
              label={t(MODULE_LABEL[m])}
              checked={d.modules.includes(m)}
              onChange={(e) => setD({ ...d, modules: e.target.checked ? [...d.modules, m] : d.modules.filter((x) => x !== m) })}
            />
          ))}
        </div>
      </fieldset>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-[13px]">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1 pr-2 font-medium">{t("admin.billing.currency")}</th>
              <th className="py-1 pr-2 font-medium">{t("admin.billing.monthly")}</th>
              <th className="py-1 pr-2 font-medium">{t("admin.billing.yearly")}</th>
              <th className="py-1 pr-2 font-medium">{t("admin.billing.seatMonthly")}</th>
              <th className="py-1 pr-2 font-medium">{t("admin.billing.overageWord")}</th>
              <th className="py-1 font-medium">{t("admin.billing.overageAi")}</th>
            </tr>
          </thead>
          <tbody>
            {currencies.map((c) => (
              <tr key={c}>
                <td className="py-1 pr-2 font-mono">{c}</td>
                <td className="py-1 pr-2">{money("prices", `month:${c}`)}</td>
                <td className="py-1 pr-2">{money("prices", `year:${c}`)}</td>
                <td className="py-1 pr-2">{money("seatPrices", `month:${c}`)}</td>
                {(["word", "ai_unit"] as const).map((u) => (
                  <td key={u} className="py-1 pr-2">
                    <Input
                      inputMode="decimal"
                      aria-label={`${c} ${u}`}
                      placeholder="0.0000"
                      value={d.overage[`${c}:${u}`] ?? ""}
                      onChange={(e) => setD({ ...d, overage: { ...d.overage, [`${c}:${u}`]: e.target.value } })}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t("admin.billing.includedWords")}>
          {(id) => <Input id={id} inputMode="numeric" value={d.includedWords} onChange={(e) => setD({ ...d, includedWords: e.target.value })} />}
        </Field>
        <Field label={t("admin.billing.includedAi")}>
          {(id) => <Input id={id} inputMode="numeric" value={d.includedAi} onChange={(e) => setD({ ...d, includedAi: e.target.value })} />}
        </Field>
        <Field label={t("admin.billing.seatsIncluded")}>
          {(id) => <Input id={id} inputMode="numeric" value={d.seats} onChange={(e) => setD({ ...d, seats: e.target.value })} />}
        </Field>
        <Field label={t("admin.billing.maxSeats")} hint={t("admin.billing.maxSeatsHint")}>
          {(id, h) => <Input id={id} aria-describedby={h} inputMode="numeric" value={d.maxSeats} onChange={(e) => setD({ ...d, maxSeats: e.target.value })} />}
        </Field>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Checkbox label={t("admin.billing.custom")} hint={t("admin.billing.customHint")} checked={d.custom} onChange={(e) => setD({ ...d, custom: e.target.checked })} />
        <Checkbox label={t("admin.billing.public")} checked={d.public} onChange={(e) => setD({ ...d, public: e.target.checked })} />
        <Checkbox label={t("admin.billing.active")} checked={d.active} onChange={(e) => setD({ ...d, active: e.target.checked })} />
      </div>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" loading={busy}>
          {t("admin.billing.save")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          {t("admin.billing.close")}
        </Button>
      </div>
    </form>
  );
}

export function PlansEditor({ plans, providers }: { plans: Plan[]; providers: ProviderStatus }) {
  const { f, t } = useI18n();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader
        title={t("admin.billing.plans")}
        description={t("admin.billing.plansHelp")}
        actions={
          <>
            <Badge tone={providers.paddle.configured ? "ok" : "neutral"}>
              {providers.paddle.configured ? t("admin.billing.paddleOn", { env: providers.paddle.environment }) : t("admin.billing.paddleOff")}
            </Badge>
            <Badge tone={providers.stripe.configured ? "ok" : "neutral"}>
              {providers.stripe.configured ? t("admin.billing.stripeOn") : t("admin.billing.stripeOff")}
            </Badge>
            <Button size="sm" onClick={() => setOpen(open === "__new" ? null : "__new")}>
              {t("admin.billing.newPlan")}
            </Button>
          </>
        }
      />
      {open === "__new" && <PlanForm plan={null} onDone={() => setOpen(null)} />}
      <Table>
        <THead>
          <tr>
            <Th>{t("admin.billing.plan")}</Th>
            <Th className="hidden md:table-cell">{t("admin.billing.modules")}</Th>
            <Th className="text-right">{t("admin.billing.monthly")}</Th>
            <Th>{t("admin.billing.visibility")}</Th>
            <Th className="text-right">
              <span className="sr-only">{t("admin.billing.edit")}</span>
            </Th>
          </tr>
        </THead>
        <TBody>
          {plans.map((p) => (
            <PlanRow key={p.key} plan={p} open={open === p.key} onToggle={() => setOpen(open === p.key ? null : p.key)} onDone={() => setOpen(null)} money={f.money} />
          ))}
        </TBody>
      </Table>
      <CardBody className="text-[12.5px] text-muted">{t("admin.billing.startingValues")}</CardBody>
    </Card>
  );
}

function PlanRow({
  plan,
  open,
  onToggle,
  onDone,
  money,
}: {
  plan: Plan;
  open: boolean;
  onToggle: () => void;
  onDone: () => void;
  money: (v: string | number | null | undefined, c?: string) => string;
}) {
  const { t } = useI18n();
  const eur = plan.prices?.month?.EUR;
  return (
    <>
      <Tr>
        <Td>
          <div className="font-medium">{plan.name}</div>
          <div className="font-mono text-[11.5px] text-faint">{plan.key}</div>
        </Td>
        <Td className="hidden md:table-cell">
          <div className="flex flex-wrap gap-1">
            {plan.modules.map((m) => (
              <Badge key={m}>{t(MODULE_LABEL[m])}</Badge>
            ))}
          </div>
        </Td>
        <Td className="tabular text-right">{plan.custom ? t("billing.plan.contract") : eur ? money(eur, "EUR") : "–"}</Td>
        <Td>
          <div className="flex flex-wrap gap-1">
            <Badge tone={plan.active ? "ok" : "danger"}>{plan.active ? t("admin.billing.active") : t("admin.billing.inactive")}</Badge>
            {!plan.public && <Badge tone="warn">{t("admin.billing.hidden")}</Badge>}
          </div>
        </Td>
        <Td className="text-right">
          <Button size="sm" variant="ghost" aria-expanded={open} onClick={onToggle}>
            {t("admin.billing.edit")}
          </Button>
        </Td>
      </Tr>
      {open && (
        <tr>
          <td colSpan={5} className="p-0">
            <PlanForm plan={plan} onDone={onDone} />
          </td>
        </tr>
      )}
    </>
  );
}
