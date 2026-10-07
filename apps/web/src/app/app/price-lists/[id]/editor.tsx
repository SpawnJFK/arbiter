"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { langName, TIER_LABEL } from "@/lib/format";
import { LANGS } from "@/lib/langs";
import { TIERS, TM_WEIGHT_KEYS, type PriceList, type Rate, type Tier, type TmWeightKey } from "@/lib/types";

const WEIGHT_LABEL: Record<TmWeightKey, string> = {
  context: "Context match (101%)",
  exact: "Exact match (100%)",
  fuzzy_95: "Fuzzy 95–99%",
  fuzzy_85: "Fuzzy 85–94%",
  fuzzy_75: "Fuzzy 75–84%",
  new: "New words",
  repetition: "Repetitions",
};
const DEFAULT_WEIGHTS: Record<TmWeightKey, string> = { context: "0", exact: "0.1", fuzzy_95: "0.3", fuzzy_85: "0.6", fuzzy_75: "0.8", new: "1", repetition: "0.1" };

type Row = { source_lang: string; target_lang: string; tier: Tier; per_word: string };

export function PriceListEditor({ priceList }: { priceList: PriceList | null }) {
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState(priceList?.name ?? "");
  const [currency, setCurrency] = useState(priceList?.currency ?? "EUR");
  const [rows, setRows] = useState<Row[]>(
    priceList?.rates.map((r) => ({ source_lang: r.source_lang ?? "", target_lang: r.target_lang ?? "", tier: r.tier, per_word: String(r.per_word) })) ??
      TIERS.map((tier, i) => ({ source_lang: "", target_lang: "", tier, per_word: ["0.03", "0.06", "0.11", "0.19"][i] })),
  );
  const [useWeights, setUseWeights] = useState(Boolean(priceList?.tm_weights));
  const [weights, setWeights] = useState<Record<TmWeightKey, string>>(() => {
    const w = { ...DEFAULT_WEIGHTS };
    for (const k of TM_WEIGHT_KEYS) if (priceList?.tm_weights?.[k] !== undefined) w[k] = String(priceList.tm_weights[k]);
    return w;
  });
  const [minimum, setMinimum] = useState(priceList?.minimum_charge ?? "");
  const [busy, setBusy] = useState(false);

  const keyOf = (r: Row) => `${r.source_lang}|${r.target_lang}|${r.tier}`;
  const dupes = rows.filter((r, i) => rows.findIndex((x) => keyOf(x) === keyOf(r)) !== i);
  const invalid = rows.filter((r) => !/^\d+(\.\d{1,5})?$/.test(r.per_word.trim()));
  const problems = [
    ...(rows.length === 0 ? ["Add at least one rate."] : []),
    ...(dupes.length ? ["Two rates have the same pair and tier."] : []),
    ...(invalid.length ? ["Rates must be numbers with up to 5 decimals, e.g. 0.085."] : []),
    ...(useWeights && TM_WEIGHT_KEYS.some((k) => !/^\d+(\.\d+)?$/.test(weights[k])) ? ["TM weights must be numbers (1 = full rate)."] : []),
  ];

  async function save() {
    if (problems.length) return;
    setBusy(true);
    const rates: Rate[] = rows.map((r) => ({ source_lang: r.source_lang || null, target_lang: r.target_lang || null, tier: r.tier, per_word: r.per_word.trim() }));
    const body = {
      name: name.trim(),
      currency: currency.toUpperCase(),
      rates,
      tm_weights: useWeights ? Object.fromEntries(TM_WEIGHT_KEYS.map((k) => [k, weights[k]])) : null,
      minimum_charge: minimum ? String(minimum) : null,
    };
    try {
      if (priceList) {
        await api.updatePriceList(priceList.id, body);
        toast.success("Price list saved");
        router.refresh();
      } else {
        const p = await api.createPriceList(body);
        toast.success("Price list created");
        router.push(`/app/price-lists/${p.id}`);
      }
    } catch (e) {
      toast.error("Could not save", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!priceList) return;
    try {
      await api.archivePriceList(priceList.id);
      toast.success("Price list archived");
      router.push("/app/price-lists");
    } catch (e) {
      toast.error("Could not archive", errorMessage(e));
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="grid gap-4 sm:grid-cols-[1fr_120px_180px]">
          <Field label="Name">{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Standard 2026" />}</Field>
          <Field label="Currency">{(id) => <Input id={id} maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value)} />}</Field>
          <Field label="Minimum charge" hint="Per project, optional">
            {(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={minimum} onChange={(e) => setMinimum(e.target.value)} placeholder="0.00" />}
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Rates per word"
          description="Leave source and target empty for a tier-wide rate. More specific rows win."
          actions={
            <Button size="sm" onClick={() => setRows([...rows, { source_lang: "", target_lang: "", tier: "hybrid", per_word: "" }])}>
              <Icons.plus className="size-3.5" /> Add rate
            </Button>
          }
        />
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[13.5px]">
            <thead className="border-b border-border bg-subtle/60 text-[12px] text-muted">
              <tr>
                <th scope="col" className="h-8 pl-4 font-medium">Source</th>
                <th scope="col" className="px-3 font-medium">Target</th>
                <th scope="col" className="px-3 font-medium">Tier</th>
                <th scope="col" className="px-3 font-medium">Per word ({currency})</th>
                <th scope="col" className="pr-4"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r, i) => {
                const upd = (patch: Partial<Row>) => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                const isDupe = dupes.includes(r);
                return (
                  <tr key={i} className={isDupe ? "bg-danger-subtle/40" : undefined}>
                    <td className="py-2 pl-4">
                      <Select aria-label={`Rate ${i + 1} source`} value={r.source_lang} onChange={(e) => upd({ source_lang: e.target.value })} className="w-40">
                        <option value="">Any source</option>
                        {LANGS.map((l) => (
                          <option key={l} value={l}>{langName(l)} ({l})</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <Select aria-label={`Rate ${i + 1} target`} value={r.target_lang} onChange={(e) => upd({ target_lang: e.target.value })} className="w-40">
                        <option value="">Any target</option>
                        {LANGS.map((l) => (
                          <option key={l} value={l}>{langName(l)} ({l})</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <Select aria-label={`Rate ${i + 1} tier`} value={r.tier} onChange={(e) => upd({ tier: e.target.value as Tier })} className="w-36">
                        {TIERS.map((t) => (
                          <option key={t} value={t}>{TIER_LABEL[t]}</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <Input aria-label={`Rate ${i + 1} per word`} inputMode="decimal" value={r.per_word} onChange={(e) => upd({ per_word: e.target.value })} className="tabular w-28" aria-invalid={invalid.includes(r)} />
                    </td>
                    <td className="py-2 pr-4 text-right">
                      <Button size="sm" variant="ghost" aria-label={`Remove rate ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                        <Icons.trash className="size-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="TM weights"
          description="Share of the full rate charged for words with a translation-memory match. Without custom weights the org defaults apply."
          actions={
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={useWeights} onChange={(e) => setUseWeights(e.target.checked)} />
              Custom weights
            </label>
          }
        />
        <CardBody className="grid gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {TM_WEIGHT_KEYS.map((k) => (
            <Field key={k} label={WEIGHT_LABEL[k]}>
              {(id) => (
                <div className="flex items-center gap-1.5">
                  <Input id={id} inputMode="decimal" disabled={!useWeights} value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: e.target.value })} className="tabular" />
                  <span className="tabular w-10 text-[12px] text-faint">{Number.isFinite(Number(weights[k])) ? `${Math.round(Number(weights[k]) * 100)}%` : ""}</span>
                </div>
              )}
            </Field>
          ))}
        </CardBody>
      </Card>

      {problems.length > 0 && (
        <Callout tone="warn">
          <ul className="list-disc pl-4">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Callout>
      )}
      <div className="flex flex-wrap justify-between gap-2">
        {priceList ? (
          <Button variant="outline-danger" onClick={archive}>
            Archive
          </Button>
        ) : (
          <span />
        )}
        <Button variant="primary" onClick={save} loading={busy} disabled={problems.length > 0 || !name.trim()}>
          {priceList ? "Save price list" : "Create price list"}
        </Button>
      </div>
    </div>
  );
}
