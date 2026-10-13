"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { VENDOR_SERVICES, type CapacityRow } from "@/lib/vendor-types";

/** "Who is free for pair X, N words, by date": the capacity planner (GET /capacity). */
export function Planner() {
  const { f, t } = useI18n();
  const toast = useToast();
  const [q, setQ] = useState({ source_lang: "en", target_lang: "", words: "5000", by: "", service: "" });
  const [rows, setRows] = useState<CapacityRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof q) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setQ((x) => ({ ...x, [key]: e.target.value }));

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.capacity({
        source_lang: q.source_lang.trim().toLowerCase(),
        target_lang: q.target_lang.trim().toLowerCase(),
        words: Number(q.words) || 1,
        by: q.by || undefined,
        service: q.service || undefined,
      });
      setRows(r.items);
    } catch (err) {
      toast.error(t("app.capacity.plannerFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title={t("app.capacity.whoIsFree")} description={t("app.capacity.whoIsFreeHint")} />
      <form onSubmit={run} className="grid gap-3 p-4 sm:grid-cols-3 lg:grid-cols-6 lg:items-end">
        <Field label={t("app.capacity.source")}>{(id) => <Input id={id} value={q.source_lang} onChange={set("source_lang")} required />}</Field>
        <Field label={t("app.capacity.target")}>{(id) => <Input id={id} value={q.target_lang} onChange={set("target_lang")} required />}</Field>
        <Field label={t("app.capacity.words")}>{(id) => <Input id={id} inputMode="numeric" value={q.words} onChange={set("words")} required />}</Field>
        <Field label={t("app.capacity.by")}>{(id) => <Input id={id} type="date" value={q.by} onChange={set("by")} />}</Field>
        <Field label={t("app.capacity.service")}>
          {(id) => (
            <Select id={id} value={q.service} onChange={set("service")}>
              <option value="">{t("app.capacity.anyService")}</option>
              {VENDOR_SERVICES.map((s) => (
                <option key={s} value={s}>
                  {t.enumLabel(s)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Button type="submit" variant="primary" loading={busy} disabled={!q.target_lang.trim()}>
          {t("app.capacity.check")}
        </Button>
      </form>
      {rows !== null &&
        (rows.length === 0 ? (
          <EmptyState title={t("app.capacity.nobodyForPair")} description={t("app.capacity.nobodyForPairHint")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.capacity.vendor")}</Th>
                <Th>{t("app.capacity.availability")}</Th>
                <Th className="text-right">{t("app.capacity.freeWords")}</Th>
                <Th className="text-right">{t("app.capacity.price")}</Th>
              </tr>
            </THead>
            <TBody>
              {rows.map((r) => (
                <Tr key={r.vendor_id}>
                  <Td>
                    <Link href={`/app/vendors/${r.vendor_id}`} className="font-medium hover:text-accent hover:underline">
                      {r.name}
                    </Link>
                    {r.absent_days.length > 0 && <div className="text-[12px] text-warn">{t("app.capacity.absentDays", { count: r.absent_days.length })}</div>}
                  </Td>
                  <Td className="text-[13px]">
                    <Badge tone={r.can_meet ? "ok" : "warn"}>{r.can_meet ? t("app.jobs.assign.canMeet") : t("app.jobs.assign.cannotMeet")}</Badge>
                    <span className="ml-2 text-muted">
                      {r.earliest_finish ? t("app.jobs.assign.finishBy", { date: f.dateOnly(r.earliest_finish) }) : t("app.jobs.assign.noFinish")}
                    </span>
                  </Td>
                  <Td className="tabular text-right">{f.num(r.free_words)}</Td>
                  <Td className="tabular text-right">{r.price ? f.money(r.price.amount, r.price.currency) : <span className="text-faint">{t("app.jobs.assign.noRate")}</span>}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        ))}
    </Card>
  );
}
