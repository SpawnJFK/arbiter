"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { DEAL_STAGES, type Account, type Deal, type DealStage } from "@/lib/types";

const DOT: Record<DealStage, string> = { lead: "bg-border-strong", qualified: "bg-info", proposal: "bg-accent", negotiation: "bg-violet", won: "bg-ok", lost: "bg-danger" };

export function DealBoard({ initial, accounts }: { initial: Deal[]; accounts: Account[] }) {
  const { f, t } = useI18n();
  const toast = useToast();
  const [deals, setDeals] = useState(initial);
  const [over, setOver] = useState<DealStage | null>(null);
  const [lost, setLost] = useState<{ deal: Deal; reason: string } | null>(null);
  const [creating, setCreating] = useState(false);

  async function move(deal: Deal, stage: DealStage, lost_reason?: string) {
    if (deal.stage === stage) return;
    if (stage === "lost" && lost_reason === undefined) {
      setLost({ deal, reason: "" });
      return;
    }
    const before = deals;
    setDeals((ds) => ds.map((d) => (d.id === deal.id ? { ...d, stage } : d)));
    try {
      const u = await api.updateDeal(deal.id, { stage, ...(lost_reason ? { lost_reason } : {}) });
      setDeals((ds) => ds.map((d) => (d.id === deal.id ? u : d)));
      toast.success(t("app.crm.deals.dealBoard.text", { title: deal.title, stage: t.enumLabel(stage) }));
    } catch (e) {
      setDeals(before);
      toast.error(t("app.crm.deals.dealBoard.couldNotMoveTheDeal"), errorMessage(e));
    }
  }

  const currency = deals[0]?.currency ?? "EUR";
  const openValue = deals.filter((d) => d.stage !== "won" && d.stage !== "lost").reduce((n, d) => n + Number(d.value), 0);

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-muted">
          {t("app.crm.deals.dealBoard.openPipeline")} <span className="tabular font-semibold text-fg">{f.money(openValue, currency)}</span>
        </span>
        <Button className="ml-auto" variant="primary" onClick={() => setCreating(true)} disabled={accounts.length === 0}>
          <Icons.plus className="size-4" /> {t("app.crm.deals.dealBoard.newDeal")}
        </Button>
      </div>
      <div className="-mx-4 overflow-x-auto px-4 pb-2 md:-mx-8 md:px-8">
        <div className="grid min-w-[1080px] grid-cols-6 gap-3">
          {DEAL_STAGES.map((stage) => {
            const col = deals.filter((d) => d.stage === stage);
            const total = col.reduce((n, d) => n + Number(d.value), 0);
            return (
              <section
                key={stage}
                aria-label={t("app.crm.deals.dealBoard.column", { stage: t.enumLabel(stage) })}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  setOver(stage);
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  setOver(null);
                  const d = deals.find((x) => x.id === e.dataTransfer.getData("text/deal-id"));
                  if (d) void move(d, stage);
                }}
                className={cn("flex min-h-72 flex-col rounded-lg border bg-subtle/50 transition-colors", over === stage ? "border-accent bg-accent-subtle/40" : "border-border")}
              >
                <header className="border-b border-border px-3 py-2">
                  <div className="flex items-center gap-2 text-[13px] font-semibold">
                    <span className={cn("size-2 rounded-full", DOT[stage])} aria-hidden="true" />
                    {t.enumLabel(stage)}
                    <span className="tabular ml-auto rounded bg-surface px-1.5 text-[11.5px] font-medium text-muted">{col.length}</span>
                  </div>
                  <div className="tabular mt-0.5 text-[12px] text-muted">{f.money(total, currency)}</div>
                </header>
                <ul className="flex flex-1 flex-col gap-2 p-2">
                  {col.map((d) => (
                    <li
                      key={d.id}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/deal-id", d.id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      className="cursor-grab rounded-md border border-border bg-surface p-2.5 shadow-card active:cursor-grabbing"
                    >
                      <div className="text-[13px] font-medium leading-snug">{d.title}</div>
                      <Link href={`/app/crm/${d.account_id}`} className="mt-0.5 block truncate text-[12px] text-muted hover:text-accent hover:underline">
                        {d.account_name ?? t("app.crm.deals.dealBoard.account")}
                      </Link>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <span className="tabular text-[13px] font-semibold">{f.money(d.value, d.currency)}</span>
                        {d.expected_close && (
                          <span className="text-[11.5px] text-faint">
                            <Time iso={d.expected_close} mode="relative" />
                          </span>
                        )}
                      </div>
                      {d.stage === "lost" && d.lost_reason && <p className="mt-1 text-[12px] text-danger">{d.lost_reason}</p>}
                      <label className="mt-2 block">
                        <span className="sr-only">{t("app.crm.deals.dealBoard.stageOf", { title: d.title })}</span>
                        <select
                          value={d.stage}
                          onChange={(e) => void move(d, e.target.value as DealStage)}
                          className="h-6 w-full rounded border border-border bg-surface px-1 text-[12px] text-muted focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          {DEAL_STAGES.map((s) => (
                            <option key={s} value={s}>
                              {t.enumLabel(s)}
                            </option>
                          ))}
                        </select>
                      </label>
                    </li>
                  ))}
                  {col.length === 0 && <li className="rounded-md border border-dashed border-border px-2 py-6 text-center text-[12px] text-faint">{t("app.crm.deals.dealBoard.dropDealsHere")}</li>}
                </ul>
              </section>
            );
          })}
        </div>
      </div>

      <Dialog
        open={lost !== null}
        onClose={() => setLost(null)}
        size="sm"
        title={t("app.crm.deals.dealBoard.markAsLost")}
        description={t("app.crm.deals.dealBoard.aShortReasonHelpsWhen")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setLost(null)}>
              {t("app.crm.deals.dealBoard.cancel")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (lost) void move(lost.deal, "lost", lost.reason.trim() || t("app.crm.deals.dealBoard.reasonNotSpecified"));
                setLost(null);
              }}
            >
              {t("app.crm.deals.dealBoard.markLost")}
            </Button>
          </>
        }
      >
        {lost && <Field label={t("app.crm.deals.dealBoard.reason")}>{(id) => <Input id={id} autoFocus value={lost.reason} onChange={(e) => setLost({ ...lost, reason: e.target.value })} placeholder={t("app.crm.deals.dealBoard.eGChoseAnIn")} />}</Field>}
      </Dialog>

      <NewDealDialog open={creating} onClose={() => setCreating(false)} accounts={accounts} onCreated={(d) => setDeals((ds) => [d, ...ds])} />
    </>
  );
}

function NewDealDialog({ open, onClose, accounts, onCreated }: { open: boolean; onClose: () => void; accounts: Account[]; onCreated: (d: Deal) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [v, setV] = useState({ account_id: accounts[0]?.id ?? "", title: "", value: "", stage: "lead" as DealStage, expected_close: "" });
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const d = await api.createDeal({ ...v, value: v.value || "0", expected_close: v.expected_close || undefined });
      onCreated(d);
      toast.success(t("app.crm.deals.dealBoard.dealCreated"));
      onClose();
      setV({ ...v, title: "", value: "" });
    } catch (err) {
      toast.error(t("app.crm.deals.dealBoard.couldNotCreateDeal"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onClose={onClose} title={t("app.crm.deals.dealBoard.newDeal")}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("app.crm.deals.dealBoard.account")}>
          {(id) => (
            <Select id={id} value={v.account_id} onChange={(e) => setV({ ...v, account_id: e.target.value })}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t("app.crm.deals.dealBoard.title")}>{(id) => <Input id={id} required value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />}</Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("app.crm.deals.dealBoard.value")}>{(id) => <Input id={id} required inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={v.value} onChange={(e) => setV({ ...v, value: e.target.value })} />}</Field>
          <Field label={t("app.crm.deals.dealBoard.stage")}>
            {(id) => (
              <Select id={id} value={v.stage} onChange={(e) => setV({ ...v, stage: e.target.value as DealStage })}>
                {DEAL_STAGES.map((s) => (
                  <option key={s} value={s}>
                    {t.enumLabel(s)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("app.crm.deals.dealBoard.expectedClose")}>{(id) => <Input id={id} type="date" value={v.expected_close} onChange={(e) => setV({ ...v, expected_close: e.target.value })} />}</Field>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("app.crm.deals.dealBoard.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            {t("app.crm.deals.dealBoard.createDeal")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
