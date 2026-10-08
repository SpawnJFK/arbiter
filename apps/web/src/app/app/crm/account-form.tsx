"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { TIERS, type Account, type AccountInput, type PriceList, type Tier, type Workflow } from "@/lib/types";

export function AccountFilters({ q, kind, status }: { q: string; kind: string; status: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const [text, setText] = useState(q);
  const go = (next: { q?: string; kind?: string; status?: string }) => {
    const sp = new URLSearchParams();
    const v = { q: text, kind, status, ...next };
    if (v.q) sp.set("q", v.q);
    if (v.kind) sp.set("kind", v.kind);
    if (v.status && v.status !== "active") sp.set("status", v.status);
    router.push(`/app/crm${sp.size ? `?${sp}` : ""}`);
  };
  return (
    <form
      className="mb-3 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        go({ q: text });
      }}
    >
      <div className="relative min-w-52 flex-1 sm:max-w-xs">
        <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
        <Input aria-label={t("app.crm.accountForm.searchAccounts")} placeholder={t("app.crm.accountForm.searchByName")} value={text} onChange={(e) => setText(e.target.value)} className="pl-8" />
      </div>
      <div role="group" aria-label={t("app.crm.accountForm.kind")} className="flex rounded-md border border-border-strong bg-surface p-0.5">
        {[
          ["", t("app.crm.accountForm.filterAll")],
          ["client", t("app.crm.accountForm.filterClients")],
          ["prospect", t("app.crm.accountForm.filterProspects")],
        ].map(([v, l]) => (
          <button key={v} type="button" aria-pressed={kind === v} onClick={() => go({ kind: v })} className={cn("h-7 rounded px-2.5 text-[13px]", kind === v ? "bg-hover font-medium text-fg" : "text-muted hover:text-fg")}>
            {l}
          </button>
        ))}
      </div>
      <Select aria-label={t("app.crm.accountForm.status")} value={status} onChange={(e) => go({ status: e.target.value })} className="w-32">
        <option value="active">{t("app.crm.accountForm.active")}</option>
        <option value="archived">{t("app.crm.accountForm.archived")}</option>
      </Select>
    </form>
  );
}

export function NewAccountButton({ workflows, priceLists }: { workflows: Workflow[]; priceLists: PriceList[] }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Icons.plus className="size-4" /> {t("app.crm.accountForm.newAccount")}
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title={t("app.crm.accountForm.newAccount")} size="lg">
        {open && <AccountForm workflows={workflows} priceLists={priceLists} onDone={() => setOpen(false)} />}
      </Dialog>
    </>
  );
}

/** Create (no `account`) or edit an account. */
export function AccountForm({
  account,
  workflows,
  priceLists,
  onDone,
}: {
  account?: Account;
  workflows: Workflow[];
  priceLists: PriceList[];
  onDone?: () => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [v, setV] = useState<AccountInput>({
    name: account?.name ?? "",
    kind: account?.kind ?? "client",
    industry: account?.industry ?? "",
    country: account?.country ?? "",
    vat_id: account?.vat_id ?? "",
    currency: account?.currency ?? "EUR",
    default_tier: account?.default_tier ?? null,
    workflow_template_id: account?.workflow_template_id ?? null,
    price_list_id: account?.price_list_id ?? null,
    notes: account?.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof AccountInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setV({ ...v, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const body: AccountInput = {
      ...v,
      industry: v.industry || null,
      country: v.country ? v.country.toUpperCase() : null,
      vat_id: v.vat_id || null,
      currency: v.currency ? v.currency.toUpperCase() : null,
      default_tier: v.default_tier || null,
      workflow_template_id: v.workflow_template_id || null,
      price_list_id: v.price_list_id || null,
      notes: v.notes ?? "",
    };
    try {
      if (account) {
        await api.updateAccount(account.id, body);
        toast.success(t("app.crm.accountForm.accountSaved"));
        router.refresh();
        onDone?.();
      } else {
        const a = await api.createAccount(body);
        toast.success(t("app.crm.accountForm.accountCreated"));
        onDone?.();
        router.push(`/app/crm/${a.id}`);
      }
    } catch (err) {
      toast.error(t("app.crm.accountForm.couldNotSaveTheAccount"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const wf = workflows.find((w) => w.id === v.workflow_template_id);
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-[1fr_160px]">
        <Field label={t("app.crm.accountForm.name")}>{(id) => <Input id={id} required value={v.name} onChange={set("name")} autoFocus={!account} />}</Field>
        <Field label={t("app.crm.accountForm.kind")}>
          {(id) => (
            <Select id={id} value={v.kind} onChange={set("kind")}>
              <option value="client">{t("app.crm.accountForm.client")}</option>
              <option value="prospect">{t("app.crm.accountForm.prospect")}</option>
            </Select>
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-4">
        <Field label={t("app.crm.accountForm.industry")} className="sm:col-span-2">
          {(id) => <Input id={id} value={v.industry ?? ""} onChange={set("industry")} placeholder={t("app.crm.accountForm.eGMedicalDevices")} />}
        </Field>
        <Field label={t("app.crm.accountForm.country")}>{(id) => <Input id={id} maxLength={2} pattern="[A-Za-z]{2}" value={v.country ?? ""} onChange={set("country")} placeholder={t("app.crm.accountForm.de")} />}</Field>
        <Field label={t("app.crm.accountForm.currency")}>{(id) => <Input id={id} maxLength={3} pattern="[A-Za-z]{3}" value={v.currency ?? ""} onChange={set("currency")} />}</Field>
      </div>
      <Field label={t("app.crm.accountForm.vatId")}>{(id) => <Input id={id} value={v.vat_id ?? ""} onChange={set("vat_id")} />}</Field>
      <fieldset className="rounded-md border border-border p-3">
        <legend className="px-1 text-[13px] font-medium">{t("app.crm.accountForm.projectDefaults")}</legend>
        <p className="mb-3 text-[12.5px] text-muted">{t("app.crm.accountForm.newProjectsForThisAccount")}</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("app.crm.accountForm.workflow")}>
            {(id) => (
              <Select id={id} value={v.workflow_template_id ?? ""} onChange={set("workflow_template_id")}>
                <option value="">{t("app.crm.accountForm.orgDefault")}</option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id} disabled={w.available === false}>
                    {w.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("app.crm.accountForm.defaultTier")} hint={wf ? t("app.crm.accountForm.comesFromTheWorkflow", { tier: t(`tier.${wf.tier}.label`) }) : undefined}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={wf ? wf.tier : v.default_tier ?? ""} disabled={Boolean(wf)} onChange={(e) => setV({ ...v, default_tier: (e.target.value || null) as Tier | null })}>
                <option value="">{t("app.crm.accountForm.orgDefault")}</option>
                {TIERS.map((tier) => (
                  <option key={tier} value={tier}>
                    {t(`tier.${tier}.label`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("app.crm.accountForm.priceList")}>
            {(id) => (
              <Select id={id} value={v.price_list_id ?? ""} onChange={set("price_list_id")}>
                <option value="">{t("app.crm.accountForm.orgDefaultPrices")}</option>
                {priceLists.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
      </fieldset>
      <Field label={t("app.crm.accountForm.notes")}>{(id) => <Textarea id={id} value={v.notes ?? ""} onChange={set("notes")} className="min-h-16" />}</Field>
      <div className="flex justify-end gap-2">
        {onDone && account === undefined && (
          <Button variant="ghost" onClick={onDone}>
            {t("app.crm.accountForm.cancel")}
          </Button>
        )}
        <Button type="submit" variant="primary" loading={busy}>
          {account ? t("app.crm.accountForm.saveSettings") : t("app.crm.accountForm.createAccount")}
        </Button>
      </div>
    </form>
  );
}
