"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { VendorService } from "@/lib/vendor-types";

export function VendorFilters({ q, status, pair }: { q: string; status: string; pair: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const [text, setText] = useState(q);
  const [pairText, setPairText] = useState(pair);
  const go = (next: { q?: string; status?: string; pair?: string }) => {
    const sp = new URLSearchParams();
    const v = { q: text, status, pair: pairText, ...next };
    if (v.q) sp.set("q", v.q);
    if (v.pair) sp.set("pair", v.pair.replace(/\s*(->|→|-)\s*/, ">").toLowerCase());
    if (v.status && v.status !== "active") sp.set("status", v.status);
    router.push(`/app/vendors${sp.size ? `?${sp}` : ""}`);
  };
  return (
    <form
      className="mb-3 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        go({});
      }}
    >
      <div className="relative min-w-52 flex-1 sm:max-w-xs">
        <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
        <Input
          aria-label={t("app.vendors.form.searchVendors")}
          placeholder={t("app.vendors.form.searchByName")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="pl-8"
        />
      </div>
      <Input
        aria-label={t("app.vendors.form.languagePair")}
        placeholder={t("app.vendors.form.pairPlaceholder")}
        value={pairText}
        onChange={(e) => setPairText(e.target.value)}
        className="w-32"
      />
      <Select aria-label={t("app.vendors.form.status")} value={status} onChange={(e) => go({ status: e.target.value })} className="w-32">
        <option value="active">{t("enum.active")}</option>
        <option value="inactive">{t("enum.inactive")}</option>
        <option value="blocked">{t("enum.blocked")}</option>
      </Select>
      <Button type="submit" size="sm">
        {t("app.vendors.form.filter")}
      </Button>
    </form>
  );
}

/** "en>de, en>fr" -> pairs with the chosen services. */
export function parsePairs(text: string, services: VendorService[]) {
  return text
    .split(/[,;\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => {
      const [s, tgt] = x.split(/\s*(?:->|→|>|-|\/)\s*/);
      return { source_lang: (s ?? "").toLowerCase(), target_lang: (tgt ?? "").toLowerCase(), services };
    })
    .filter((p) => p.source_lang && p.target_lang);
}

export function NewVendorButton() {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "",
    kind: "person" as "person" | "company",
    email: "",
    pairs: "",
    translation: "",
    review: "",
    currency: "EUR",
    capacity: "2500",
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save() {
    setBusy(true);
    try {
      const rates = [
        ...(form.translation ? [{ service: "translation" as const, unit: "word" as const, rate: form.translation, source_lang: null, target_lang: null }] : []),
        ...(form.review ? [{ service: "review" as const, unit: "word" as const, rate: form.review, source_lang: null, target_lang: null }] : []),
      ];
      const v = await api.createVendor({
        name: form.name.trim(),
        kind: form.kind,
        email: form.email.trim() || null,
        pairs: parsePairs(form.pairs, ["translation", "review"]),
        rates,
        currency: form.currency.trim().toUpperCase() || "EUR",
        capacity_words_per_day: Number(form.capacity) || 0,
      });
      toast.success(t("app.vendors.form.created"), v.name);
      setOpen(false);
      router.push(`/app/vendors/${v.id}`);
    } catch (e) {
      toast.error(t("app.vendors.form.couldNotSave"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Icons.plus className="size-4" /> {t("app.vendors.form.newVendor")}
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={t("app.vendors.form.newVendor")}
        description={t("app.vendors.form.newVendorHint")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("app.vendors.form.cancel")}
            </Button>
            <Button variant="primary" onClick={save} loading={busy} disabled={!form.name.trim()}>
              {t("app.vendors.form.create")}
            </Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("app.vendors.form.name")} className="sm:col-span-2">
            {(id) => <Input id={id} value={form.name} onChange={set("name")} required />}
          </Field>
          <Field label={t("app.vendors.form.kind")}>
            {(id) => (
              <Select id={id} value={form.kind} onChange={set("kind")}>
                <option value="person">{t("enum.person")}</option>
                <option value="company">{t("enum.company")}</option>
              </Select>
            )}
          </Field>
          <Field label={t("app.vendors.form.email")}>
            {(id) => <Input id={id} type="email" value={form.email} onChange={set("email")} />}
          </Field>
          <Field label={t("app.vendors.form.pairs")} hint={t("app.vendors.form.pairsHint")} className="sm:col-span-2">
            {(id, d) => <Input id={id} aria-describedby={d} value={form.pairs} onChange={set("pairs")} placeholder="en>de, en>fr" />}
          </Field>
          <Field label={t("app.vendors.form.translationRate")}>
            {(id) => <Input id={id} inputMode="decimal" value={form.translation} onChange={set("translation")} placeholder="0.08" />}
          </Field>
          <Field label={t("app.vendors.form.reviewRate")}>
            {(id) => <Input id={id} inputMode="decimal" value={form.review} onChange={set("review")} placeholder="0.03" />}
          </Field>
          <Field label={t("app.vendors.form.currency")}>
            {(id) => <Input id={id} value={form.currency} onChange={set("currency")} maxLength={3} />}
          </Field>
          <Field label={t("app.vendors.form.capacity")}>
            {(id) => <Input id={id} inputMode="numeric" value={form.capacity} onChange={set("capacity")} />}
          </Field>
        </div>
      </Dialog>
    </>
  );
}

export function ImportVendorsButton() {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ created: number; updated: number; errors: { row: number; error: string }[] } | null>(null);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      const r = await api.importVendors(file);
      setResult(r);
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendors.form.importFailed"), errorMessage(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" aria-label={t("app.vendors.form.importCsv")} onChange={(e) => onFile(e.target.files?.[0])} />
      <Button onClick={() => input.current?.click()} loading={busy}>
        <Icons.upload className="size-4" /> {t("app.vendors.form.importCsv")}
      </Button>
      <Dialog open={result !== null} onClose={() => setResult(null)} title={t("app.vendors.form.importDone")} size="sm">
        {result && (
          <div className="space-y-3 text-[13.5px]">
            <p>{t("app.vendors.form.importSummary", { created: result.created, updated: result.updated })}</p>
            {result.errors.length > 0 && (
              <Callout tone="warn" title={t("app.vendors.form.rowsSkipped", { count: result.errors.length })}>
                <ul className="space-y-0.5">
                  {result.errors.slice(0, 10).map((e) => (
                    <li key={e.row}>{t("app.vendors.form.rowError", { row: e.row, error: e.error })}</li>
                  ))}
                </ul>
              </Callout>
            )}
            <p className="text-[12.5px] text-muted">{t("app.vendors.form.csvColumns")}</p>
          </div>
        )}
      </Dialog>
    </>
  );
}
