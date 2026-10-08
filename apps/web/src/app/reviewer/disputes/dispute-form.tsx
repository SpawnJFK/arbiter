"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { api, errorMessage } from "@/lib/api";

export function DisputeForm({ initialTaskId }: { initialTaskId: string }) {
  const { t } = useI18n();
  const [taskId, setTaskId] = useState(initialTaskId);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: string; due_at: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(await api.createDispute({ task_id: taskId.trim(), reason: reason.trim() }));
      setReason("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="max-w-2xl">
      <CardBody>
        {created && (
          <Callout tone="ok" title={t("reviewer.disputes.disputeForm.disputeOpened")} className="mb-4">
            {t("reviewer.disputes.disputeForm.reference")} <span className="font-mono">{created.id}</span>{t("reviewer.disputes.disputeForm.aDecisionIsDueBy")} <Time iso={created.due_at} />.
          </Callout>
        )}
        {error && (
          <Callout tone="danger" className="mb-4">
            {error}
          </Callout>
        )}
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("reviewer.disputes.disputeForm.taskId")} hint={t("reviewer.disputes.disputeForm.shownOnTheLedgerEntry")}>
            {(id, d) => <Input id={id} aria-describedby={d} required pattern="tsk_.+" className="font-mono" value={taskId} onChange={(e) => setTaskId(e.target.value)} />}
          </Field>
          <Field label={t("reviewer.disputes.disputeForm.whatShouldBeReconsideredAnd")} hint={t("reviewer.disputes.disputeForm.beSpecificQuoteTheSegment")}>
            {(id, d) => <Textarea id={id} aria-describedby={d} required minLength={20} className="min-h-32" value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" loading={busy} disabled={!taskId.trim() || reason.trim().length < 20}>
            {t("reviewer.disputes.disputeForm.openDispute")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
