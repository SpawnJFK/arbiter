"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { api, errorMessage } from "@/lib/api";

export function DisputeForm({ initialTaskId }: { initialTaskId: string }) {
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
          <Callout tone="ok" title="Dispute opened" className="mb-4">
            Reference <span className="font-mono">{created.id}</span>. A decision is due by <Time iso={created.due_at} />.
          </Callout>
        )}
        {error && (
          <Callout tone="danger" className="mb-4">
            {error}
          </Callout>
        )}
        <form onSubmit={submit} className="space-y-4">
          <Field label="Task ID" hint="Shown on the ledger entry, e.g. tsk_01J…">
            {(id, d) => <Input id={id} aria-describedby={d} required pattern="tsk_.+" className="font-mono" value={taskId} onChange={(e) => setTaskId(e.target.value)} />}
          </Field>
          <Field label="What should be reconsidered, and why?" hint="Be specific: quote the segment, the glossary entry or the rule you relied on.">
            {(id, d) => <Textarea id={id} aria-describedby={d} required minLength={20} className="min-h-32" value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" loading={busy} disabled={!taskId.trim() || reason.trim().length < 20}>
            Open dispute
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
