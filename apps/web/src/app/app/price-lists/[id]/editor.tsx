"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import { TIERS, TM_WEIGHT_KEYS, type PriceList, type Rate, type Tier, type TmWeightKey } from "@/lib/types";

const WEIGHT_LABEL: Record<TmWeightKey, string> = {
  context: k("app.priceLists.detail.editor.weight.context"),
  exact: k("app.priceLists.detail.editor.weight.exact"),
  fuzzy_95: k("app.priceLists.detail.editor.weight.fuzzy_95"),
  fuzzy_85: k("app.priceLists.detail.editor.weight.fuzzy_85"),
  fuzzy_75: k("app.priceLists.detail.editor.weight.fuzzy_75"),
  new: k("app.priceLists.detail.editor.weight.new"),
  repetition: k("app.priceLists.detail.editor.weight.repetition"),
};
const DEFAULT_WEIGHTS: Record<TmWeightKey, string> = { context: "0", exact: "0.1", fuzzy_95: "0.3", fuzzy_85: "0.6", fuzzy_75: "0.8", new: "1", repetition: "0.1" };

type Row = { source_lang: string; target_lang: string; tier: Tier; per_word: string };

export function PriceListEditor({ priceList }: { priceList: PriceList | null }) {
  const { f, t } = useI18n();
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
    ...(rows.length === 0 ? [t("app.priceLists.detail.editor.problemNoRates")] : []),
    ...(dupes.length ? [t("app.priceLists.detail.editor.problemDuplicate")] : []),
    ...(invalid.length ? [t("app.priceLists.detail.editor.problemRateFormat")] : []),
    ...(useWeights && TM_WEIGHT_KEYS.some((k) => !/^\d+(\.\d+)?$/.test(weights[k])) ? [t("app.priceLists.detail.editor.problemWeights")] : []),
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
        toast.success(t("app.priceLists.detail.editor.priceListSaved"));
        router.refresh();
      } else {
        const p = await api.createPriceList(body);
        toast.success(t("app.priceLists.detail.editor.priceListCreated"));
        router.push(`/app/price-lists/${p.id}`);
      }
    } catch (e) {
      toast.error(t("app.priceLists.detail.editor.couldNotSave"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!priceList) return;
    try {
      await api.archivePriceList(priceList.id);
      toast.success(t("app.priceLists.detail.editor.priceListArchived"));
      router.push("/app/price-lists");
    } catch (e) {
      toast.error(t("app.priceLists.detail.editor.couldNotArchive"), errorMessage(e));
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="grid gap-4 sm:grid-cols-[1fr_120px_180px]">
          <Field label={t("app.priceLists.detail.editor.name")}>{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} placeholder={t("app.priceLists.detail.editor.eGStandard2026")} />}</Field>
          <Field label={t("app.priceLists.detail.editor.currency")}>{(id) => <Input id={id} maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value)} />}</Field>
          <Field label={t("app.priceLists.detail.editor.minimumCharge")} hint={t("app.priceLists.detail.editor.perProjectOptional")}>
            {(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={minimum} onChange={(e) => setMinimum(e.target.value)} placeholder="0.00" />}
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("app.priceLists.detail.editor.ratesPerWord")}
          description={t("app.priceLists.detail.editor.leaveSourceAndTargetEmpty")}
          actions={
            <Button size="sm" onClick={() => setRows([...rows, { source_lang: "", target_lang: "", tier: "hybrid", per_word: "" }])}>
              <Icons.plus className="size-3.5" /> {t("app.priceLists.detail.editor.addRate")}
            </Button>
          }
        />
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[13.5px]">
            <thead className="border-b border-border bg-subtle/60 text-[12px] text-muted">
              <tr>
                <th scope="col" className="h-8 pl-4 font-medium">{t("app.priceLists.detail.editor.source")}</th>
                <th scope="col" className="px-3 font-medium">{t("app.priceLists.detail.editor.target")}</th>
                <th scope="col" className="px-3 font-medium">{t("app.priceLists.detail.editor.tier")}</th>
                <th scope="col" className="px-3 font-medium">{t("app.priceLists.detail.editor.perWord", { currency: currency })}</th>
                <th scope="col" className="pr-4"><span className="sr-only">{t("app.priceLists.detail.editor.remove")}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r, i) => {
                const upd = (patch: Partial<Row>) => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                const isDupe = dupes.includes(r);
                return (
                  <tr key={i} className={isDupe ? "bg-danger-subtle/40" : undefined}>
                    <td className="py-2 pl-4">
                      <Select aria-label={t("app.priceLists.detail.editor.rateSource", { value: i + 1 })} value={r.source_lang} onChange={(e) => upd({ source_lang: e.target.value })} className="w-40">
                        <option value="">{t("app.priceLists.detail.editor.anySource")}</option>
                        {LANGS.map((l) => (
                          <option key={l} value={l}>{f.langName(l)} ({l})</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <Select aria-label={t("app.priceLists.detail.editor.rateTarget", { value: i + 1 })} value={r.target_lang} onChange={(e) => upd({ target_lang: e.target.value })} className="w-40">
                        <option value="">{t("app.priceLists.detail.editor.anyTarget")}</option>
                        {LANGS.map((l) => (
                          <option key={l} value={l}>{f.langName(l)} ({l})</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <Select aria-label={t("app.priceLists.detail.editor.rateTier", { value: i + 1 })} value={r.tier} onChange={(e) => upd({ tier: e.target.value as Tier })} className="w-36">
                        {TIERS.map((tier) => (
                          <option key={tier} value={tier}>{t(`tier.${tier}.label`)}</option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-2">
                      <Input aria-label={t("app.priceLists.detail.editor.ratePerWord", { value: i + 1 })} inputMode="decimal" value={r.per_word} onChange={(e) => upd({ per_word: e.target.value })} className="tabular w-28" aria-invalid={invalid.includes(r)} />
                    </td>
                    <td className="py-2 pr-4 text-right">
                      <Button size="sm" variant="ghost" aria-label={t("app.priceLists.detail.editor.removeRate", { value: i + 1 })} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
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
          title={t("app.priceLists.detail.editor.tmWeights")}
          description={t("app.priceLists.detail.editor.shareOfTheFullRate")}
          actions={
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={useWeights} onChange={(e) => setUseWeights(e.target.checked)} />
              {t("app.priceLists.detail.editor.customWeights")}
            </label>
          }
        />
        <CardBody className="grid gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {TM_WEIGHT_KEYS.map((k) => (
            <Field key={k} label={t(WEIGHT_LABEL[k])}>
              {(id) => (
                <div className="flex items-center gap-1.5">
                  <Input id={id} inputMode="decimal" disabled={!useWeights} value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: e.target.value })} className="tabular" />
                  <span className="tabular w-10 text-[12px] text-faint">{Number.isFinite(Number(weights[k])) ? f.pct(Number(weights[k])) : ""}</span>
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
            {t("app.priceLists.detail.editor.archive")}
          </Button>
        ) : (
          <span />
        )}
        <Button variant="primary" onClick={save} loading={busy} disabled={problems.length > 0 || !name.trim()}>
          {priceList ? t("app.priceLists.detail.editor.savePriceList") : t("app.priceLists.detail.editor.createPriceList")}
        </Button>
      </div>
    </div>
  );
}
