"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Dispute } from "@/lib/types";

export function DisputesList({ initial }: { initial: Dispute[] }) {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState(initial);
  const [deciding, setDeciding] = useState<{ d: Dispute; outcome: "upheld" | "overturned" } | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function decide() {
    if (!deciding || !note.trim()) return;
    setBusy(true);
    try {
      const res = await api.decideDispute(deciding.d.id, { outcome: deciding.outcome, note: note.trim() });
      setRows((xs) => xs.map((x) => (x.id === res.id ? { ...x, ...res } : x)));
      toast.success(t("admin.disputes.disputesList.dispute", { outcome: deciding.outcome }));
      setDeciding(null);
      setNote("");
    } catch (e) {
      toast.error(t("admin.disputes.disputesList.couldNotDecide"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const open = rows.filter((r) => r.status === "open");
  const closed = rows.filter((r) => r.status !== "open");

  return (
    <div className="space-y-4">
      <Card>
        {open.length === 0 ? (
          <EmptyState title={t("admin.disputes.disputesList.noOpenDisputes")} />
        ) : (
          <ul className="divide-y divide-border">
            {open.map((d) => (
              <li key={d.id} className="flex flex-col gap-3 px-4 py-3 md:flex-row md:items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                    <span className="font-mono">{d.id}</span>·<span className="font-mono">{d.task_id}</span>
                    {d.reviewer_id && (
                      <>
                        ·<span className="font-mono">{d.reviewer_id}</span>
                      </>
                    )}
                  </div>
                  <p className="mt-1 text-[14px]">{d.reason}</p>
                  <p className="mt-1 text-[12.5px] text-muted">
                    {t("admin.disputes.disputesList.due")} <Time iso={d.due_at} mode="relative" />
                  </p>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button size="sm" onClick={() => setDeciding({ d, outcome: "upheld" })}>
                    {t("admin.disputes.disputesList.uphold")}
                  </Button>
                  <Button size="sm" variant="outline-danger" onClick={() => setDeciding({ d, outcome: "overturned" })}>
                    {t("admin.disputes.disputesList.overturn")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {closed.length > 0 && (
        <Card>
          <div className="border-b border-border px-4 py-2.5 text-[13px] font-medium text-muted">{t("admin.disputes.disputesList.decided")}</div>
          <ul className="divide-y divide-border">
            {closed.map((d) => (
              <li key={d.id} className="px-4 py-2.5 text-[13.5px]">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={d.status} />
                  <span className="font-mono text-[12.5px] text-muted">{d.task_id}</span>
                </div>
                {d.decision_note && <p className="mt-1 text-muted">{d.decision_note}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Dialog
        open={deciding !== null}
        onClose={() => setDeciding(null)}
        title={deciding?.outcome === "upheld" ? t("admin.disputes.disputesList.upholdDisputeReviewerIsRight") : t("admin.disputes.disputesList.overturnDisputeOriginalDecisionStands")}
        description={t("admin.disputes.disputesList.theNoteIsShownTo")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeciding(null)}>
              {t("admin.disputes.disputesList.cancel")}
            </Button>
            <Button variant={deciding?.outcome === "overturned" ? "danger" : "primary"} onClick={decide} loading={busy} disabled={!note.trim()}>
              {deciding?.outcome === "upheld" ? t("admin.disputes.disputesList.uphold") : t("admin.disputes.disputesList.overturn")}
            </Button>
          </>
        }
      >
        {deciding && (
          <div className="space-y-3">
            <p className={cn("rounded-md bg-subtle p-3 text-[13.5px]")}>{deciding.d.reason}</p>
            <Field label={t("admin.disputes.disputesList.decisionNote")}>{(id) => <Textarea id={id} required value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
          </div>
        )}
      </Dialog>
    </div>
  );
}
