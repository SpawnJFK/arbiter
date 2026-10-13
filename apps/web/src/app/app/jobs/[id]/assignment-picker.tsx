"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CopyField } from "@/components/copy-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { HumanStep, JobAssignments, Suggestions } from "@/lib/vendor-types";
import { ASSIGNMENT_TONE } from "../../vendors/[id]/vendor-profile";

type Mode = "marketplace" | "vendor" | "internal";

/**
 * Who does the job's human steps: the reviewer marketplace (default), own vendors (ranked
 * offer, first to accept wins) or the PM themself. Shows ranked vendor suggestions with
 * price and availability (module pm).
 */
export function AssignmentPicker({ jobId, userId, locked = false }: { jobId: string; userId: string; locked?: boolean }) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [data, setData] = useState<JobAssignments | null>(null);
  const [step, setStep] = useState<HumanStep>("human_review");
  const [mode, setMode] = useState<Mode>("vendor");
  const [sugg, setSugg] = useState<Suggestions | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<"sequential" | "broadcast">("sequential");
  const [timeout, setTimeoutMin] = useState("240");
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      const a = await api.jobAssignments(jobId);
      setData(a);
      if (!a.routes[step]) return;
      setSugg(await api.assignmentSuggestions(jobId, step));
    } catch {
      setUnavailable(true); // module off or not a pm: the picker simply does not show
    }
  }, [jobId, step]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  if (unavailable || !data) return null;
  const steps = Object.keys(data.routes) as HumanStep[];
  if (steps.length === 0) return null;
  const route = data.routes[step];
  const rows = data.items.filter((a) => a.step === step);
  if (locked && data.items.length === 0) return null;

  async function submit() {
    setBusy(true);
    try {
      await api.createAssignment(jobId, {
        step,
        mode,
        vendor_ids: mode === "vendor" ? picked : undefined,
        user_id: mode === "internal" ? userId : undefined,
        strategy,
        offer_timeout_minutes: Number(timeout),
      });
      toast.success(
        mode === "marketplace" ? t("app.jobs.assign.backToMarketplace") : mode === "internal" ? t("app.jobs.assign.assignedToYou") : t("app.jobs.assign.offerSent"),
      );
      setPicked([]);
      await load();
      router.refresh();
    } catch (e) {
      toast.error(t("app.jobs.assign.couldNotAssign"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function act(id: string, action: "approve" | "reopen" | "cancel") {
    try {
      if (action === "approve") await api.approveAssignment(id);
      else if (action === "reopen") await api.reopenAssignment(id);
      else await api.cancelAssignment(id);
      await load();
      router.refresh();
    } catch (e) {
      toast.error(t("app.jobs.assign.couldNotUpdate"), errorMessage(e));
    }
  }

  const togglePick = (id: string) => setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(0, 5)));

  return (
    <Card className="mb-4">
      <CardHeader
        title={t("app.jobs.assign.title")}
        description={t("app.jobs.assign.description")}
        actions={
          <span className="flex items-center gap-2 text-[13px]">
            {steps.length > 1 && (
              <Select aria-label={t("app.jobs.assign.step")} value={step} onChange={(e) => setStep(e.target.value as HumanStep)} className="w-44">
                {steps.map((s) => (
                  <option key={s} value={s}>
                    {t.enumLabel(s)}
                  </option>
                ))}
              </Select>
            )}
            <span className="text-muted">{t("app.jobs.assign.currentRoute")}</span>
            <Badge tone={route?.mode === "marketplace" ? "neutral" : "accent"}>{t.enumLabel(route?.mode ?? "marketplace")}</Badge>
          </span>
        }
      />
      {rows.length > 0 && (
        <Table>
          <THead>
            <tr>
              <Th>{t("app.jobs.assign.assignee")}</Th>
              <Th>{t("app.jobs.assign.status")}</Th>
              <Th className="text-right">{t("app.jobs.assign.words")}</Th>
              <Th className="text-right">{t("app.jobs.assign.fee")}</Th>
              <Th className="hidden md:table-cell">{t("app.jobs.assign.po")}</Th>
              <Th />
            </tr>
          </THead>
          <TBody>
            {rows.map((a) => (
              <Tr key={a.id}>
                <Td>
                  {a.vendor_id ? (
                    <Link href={`/app/vendors/${a.vendor_id}`} className="font-medium hover:text-accent hover:underline">
                      {a.vendor_name}
                    </Link>
                  ) : (
                    <span className="font-medium">{a.user_name}</span>
                  )}
                  <div className="text-[12px] text-faint">
                    {a.assignee_kind === "internal" ? t("app.jobs.assign.internal") : t("app.jobs.assign.rank", { rank: a.rank + 1 })}
                  </div>
                </Td>
                <Td>
                  <Badge tone={ASSIGNMENT_TONE[a.status]}>{t.enumLabel(a.status)}</Badge>
                </Td>
                <Td className="tabular text-right">
                  {f.num(a.words_done)} / {f.num(a.words)}
                </Td>
                <Td className="tabular text-right">{a.assignee_kind === "vendor" ? f.money(a.amount, a.currency) : "–"}</Td>
                <Td className="hidden font-mono text-[12.5px] md:table-cell">{a.po_number ?? "–"}</Td>
                <Td className="text-right">
                  <span className="inline-flex gap-1">
                    {a.status === "delivered" && (
                      <>
                        <Button size="sm" variant="primary" onClick={() => act(a.id, "approve")}>
                          {t("app.jobs.assign.approve")}
                        </Button>
                        <Button size="sm" onClick={() => act(a.id, "reopen")}>
                          {t("app.jobs.assign.sendBack")}
                        </Button>
                      </>
                    )}
                    {["pending", "offered", "accepted", "in_progress"].includes(a.status) && (
                      <Button size="sm" variant="ghost" onClick={() => act(a.id, "cancel")}>
                        {t("app.jobs.assign.cancel")}
                      </Button>
                    )}
                  </span>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
      {rows
        .filter((a) => a.link && ["offered", "accepted", "in_progress"].includes(a.status))
        .slice(0, 1)
        .map((a) => (
          <div key={a.id} className="border-t border-border px-4 py-3">
            <div className="mb-1 text-[12.5px] text-muted">{t("app.jobs.assign.workbenchLink", { name: a.vendor_name ?? a.user_name ?? "" })}</div>
            <CopyField value={a.link ?? ""} label={t("app.jobs.assign.workbenchLinkLabel")} />
          </div>
        ))}

      {!locked && (
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
        <div role="group" aria-label={t("app.jobs.assign.mode")} className="flex rounded-md border border-border-strong bg-surface p-0.5">
          {(["marketplace", "vendor", "internal"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={cn("h-7 rounded px-2.5 text-[13px]", mode === m ? "bg-hover font-medium text-fg" : "text-muted hover:text-fg")}
            >
              {m === "marketplace" ? t("app.jobs.assign.modeMarketplace") : m === "vendor" ? t("app.jobs.assign.modeVendor") : t("app.jobs.assign.modeInternal")}
            </button>
          ))}
        </div>
        {mode === "vendor" && (
          <>
            <Select aria-label={t("app.jobs.assign.strategy")} value={strategy} onChange={(e) => setStrategy(e.target.value as "sequential" | "broadcast")} className="w-48">
              <option value="sequential">{t("app.jobs.assign.sequential")}</option>
              <option value="broadcast">{t("app.jobs.assign.broadcast")}</option>
            </Select>
            <Select aria-label={t("app.jobs.assign.timeout")} value={timeout} onChange={(e) => setTimeoutMin(e.target.value)} className="w-40">
              {["60", "240", "1440"].map((m) => (
                <option key={m} value={m}>
                  {t("app.jobs.assign.timeoutHours", { hours: Number(m) / 60 })}
                </option>
              ))}
            </Select>
          </>
        )}
        <Button
          variant="primary"
          className="ml-auto"
          loading={busy}
          disabled={mode === "vendor" && picked.length === 0}
          onClick={submit}
        >
          {mode === "marketplace"
            ? t("app.jobs.assign.useMarketplace")
            : mode === "internal"
              ? t("app.jobs.assign.assignToMe")
              : t("app.jobs.assign.sendOffer", { count: picked.length })}
        </Button>
      </div>

      )}

      {!locked && mode === "vendor" &&
        (sugg && sugg.items.length > 0 ? (
          <Table>
            <THead>
              <tr>
                <Th className="w-10">{t("app.jobs.assign.order")}</Th>
                <Th>{t("app.jobs.assign.vendor")}</Th>
                <Th>{t("app.jobs.assign.availability")}</Th>
                <Th className="hidden text-right sm:table-cell">{t("app.jobs.assign.freeWords")}</Th>
                <Th className="text-right">{t("app.jobs.assign.price")}</Th>
              </tr>
            </THead>
            <TBody>
              {sugg.items.map((r) => {
                const pos = picked.indexOf(r.vendor_id);
                return (
                  <Tr key={r.vendor_id} className={cn(!r.eligible && "opacity-50")}>
                    <Td>
                      <button
                        type="button"
                        disabled={!r.eligible || !r.price}
                        aria-pressed={pos >= 0}
                        aria-label={t("app.jobs.assign.pick", { name: r.name })}
                        onClick={() => togglePick(r.vendor_id)}
                        className={cn(
                          "tabular flex size-6 items-center justify-center rounded-md border text-[12px] font-semibold disabled:cursor-not-allowed",
                          pos >= 0 ? "border-accent bg-accent text-accent-fg" : "border-border-strong text-faint hover:border-accent",
                        )}
                      >
                        {pos >= 0 ? pos + 1 : "+"}
                      </button>
                    </Td>
                    <Td>
                      <span className="font-medium">{r.name}</span>
                      <div className="text-[12px] text-faint">
                        {!r.eligible ? t("app.jobs.assign.didFirstReview") : r.nda_signed ? t("app.jobs.assign.ndaOnFile") : t("app.jobs.assign.noNda")}
                        {r.rating ? ` · ${t("app.jobs.assign.ratingValue", { rating: r.rating })}` : ""}
                      </div>
                    </Td>
                    <Td className="text-[13px]">
                      <Badge tone={r.can_meet ? "ok" : "warn"}>{r.can_meet ? t("app.jobs.assign.canMeet") : t("app.jobs.assign.cannotMeet")}</Badge>
                      <span className="ml-2 text-muted">
                        {r.earliest_finish ? t("app.jobs.assign.finishBy", { date: f.dateOnly(r.earliest_finish) }) : t("app.jobs.assign.noFinish")}
                      </span>
                    </Td>
                    <Td className="tabular hidden text-right sm:table-cell">{f.num(r.free_words)}</Td>
                    <Td className="tabular text-right">{r.price ? f.money(r.price.amount, r.price.currency) : <span className="text-faint">{t("app.jobs.assign.noRate")}</span>}</Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        ) : (
          <EmptyState
            title={t("app.jobs.assign.noVendors")}
            description={t("app.jobs.assign.noVendorsHint")}
            action={
              <Link href="/app/vendors" className="text-[13px] font-medium text-accent hover:underline">
                {t("app.jobs.assign.manageVendors")}
              </Link>
            }
          />
        ))}
    </Card>
  );
}
