"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { TIER_LABEL } from "@/lib/format";
import { TIERS, type Account, type AccountInput, type PriceList, type Tier, type Workflow } from "@/lib/types";

export function AccountFilters({ q, kind, status }: { q: string; kind: string; status: string }) {
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
        <Input aria-label="Search accounts" placeholder="Search by name" value={text} onChange={(e) => setText(e.target.value)} className="pl-8" />
      </div>
      <div role="group" aria-label="Kind" className="flex rounded-md border border-border-strong bg-surface p-0.5">
        {[
          ["", "All"],
          ["client", "Clients"],
          ["prospect", "Prospects"],
        ].map(([v, l]) => (
          <button key={v} type="button" aria-pressed={kind === v} onClick={() => go({ kind: v })} className={cn("h-7 rounded px-2.5 text-[13px]", kind === v ? "bg-hover font-medium text-fg" : "text-muted hover:text-fg")}>
            {l}
          </button>
        ))}
      </div>
      <Select aria-label="Status" value={status} onChange={(e) => go({ status: e.target.value })} className="w-32">
        <option value="active">Active</option>
        <option value="archived">Archived</option>
      </Select>
    </form>
  );
}

export function NewAccountButton({ workflows, priceLists }: { workflows: Workflow[]; priceLists: PriceList[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Icons.plus className="size-4" /> New account
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="New account" size="lg">
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
        toast.success("Account saved");
        router.refresh();
        onDone?.();
      } else {
        const a = await api.createAccount(body);
        toast.success("Account created");
        onDone?.();
        router.push(`/app/crm/${a.id}`);
      }
    } catch (err) {
      toast.error("Could not save the account", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const wf = workflows.find((w) => w.id === v.workflow_template_id);
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-[1fr_160px]">
        <Field label="Name">{(id) => <Input id={id} required value={v.name} onChange={set("name")} autoFocus={!account} />}</Field>
        <Field label="Kind">
          {(id) => (
            <Select id={id} value={v.kind} onChange={set("kind")}>
              <option value="client">Client</option>
              <option value="prospect">Prospect</option>
            </Select>
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-4">
        <Field label="Industry" className="sm:col-span-2">
          {(id) => <Input id={id} value={v.industry ?? ""} onChange={set("industry")} placeholder="e.g. Medical devices" />}
        </Field>
        <Field label="Country">{(id) => <Input id={id} maxLength={2} pattern="[A-Za-z]{2}" value={v.country ?? ""} onChange={set("country")} placeholder="DE" />}</Field>
        <Field label="Currency">{(id) => <Input id={id} maxLength={3} pattern="[A-Za-z]{3}" value={v.currency ?? ""} onChange={set("currency")} />}</Field>
      </div>
      <Field label="VAT ID">{(id) => <Input id={id} value={v.vat_id ?? ""} onChange={set("vat_id")} />}</Field>
      <fieldset className="rounded-md border border-border p-3">
        <legend className="px-1 text-[13px] font-medium">Project defaults</legend>
        <p className="mb-3 text-[12.5px] text-muted">New projects for this account start with these. A workflow sets the tier.</p>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Workflow">
            {(id) => (
              <Select id={id} value={v.workflow_template_id ?? ""} onChange={set("workflow_template_id")}>
                <option value="">Org default</option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id} disabled={w.available === false}>
                    {w.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Default tier" hint={wf ? `Comes from the workflow: ${TIER_LABEL[wf.tier]}` : undefined}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={wf ? wf.tier : v.default_tier ?? ""} disabled={Boolean(wf)} onChange={(e) => setV({ ...v, default_tier: (e.target.value || null) as Tier | null })}>
                <option value="">Org default</option>
                {TIERS.map((t) => (
                  <option key={t} value={t}>
                    {TIER_LABEL[t]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Price list">
            {(id) => (
              <Select id={id} value={v.price_list_id ?? ""} onChange={set("price_list_id")}>
                <option value="">Org default prices</option>
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
      <Field label="Notes">{(id) => <Textarea id={id} value={v.notes ?? ""} onChange={set("notes")} className="min-h-16" />}</Field>
      <div className="flex justify-end gap-2">
        {onDone && account === undefined && (
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        )}
        <Button type="submit" variant="primary" loading={busy}>
          {account ? "Save settings" : "Create account"}
        </Button>
      </div>
    </form>
  );
}
