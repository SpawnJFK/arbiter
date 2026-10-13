"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useState } from "react";
import { TaggedText } from "@/components/tagged-text";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { QueryItem } from "@/lib/types-workbench";

export function QueriesInbox({ initial }: { initial: QueryItem[] }) {
  const { t } = useI18n();
  const [items, setItems] = useState(initial);
  if (items.length === 0) return <Card><EmptyState title={t("app.queries.empty")} description={t("app.queries.emptyHint")} /></Card>;
  return (
    <div className="space-y-3">
      {items.map((q) => (
        <QueryCard key={q.id} q={q} onChange={(n) => setItems((xs) => (n ? xs.map((x) => (x.id === n.id ? n : x)) : xs.filter((x) => x.id !== q.id)))} />
      ))}
    </div>
  );
}

function QueryCard({ q, onChange }: { q: QueryItem; onChange: (next: QueryItem | null) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!answer.trim()) return;
    setBusy(true);
    try {
      const reply = await api.addComment(q.job_id, { body: answer, parent_id: q.id });
      setAnswer("");
      onChange({ ...q, replies: [...q.replies, reply] });
      toast.success(t("app.queries.sent"));
    } catch (err) {
      toast.error(t("app.queries.failed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function resolve() {
    try {
      await api.resolveComment(q.id, true);
      onChange(null);
    } catch (err) {
      toast.error(t("app.queries.failed"), errorMessage(err));
    }
  }

  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
        <Link href={`/app/jobs/${q.job_id}`} className="font-medium text-fg hover:underline">
          {q.filename ?? q.job_id}
        </Link>
        {q.segment_seq !== null && <span>{t("app.queries.segment", { n: q.segment_seq + 1 })}</span>}
        <span className="ml-auto">
          <Time iso={q.created_at} mode="relative" />
        </span>
      </div>
      {q.source_tagged && (
        <div className="mb-2 grid gap-2 rounded-md bg-subtle/60 p-2.5 text-[13.5px] sm:grid-cols-2">
          <TaggedText value={q.source_tagged} className="text-muted" />
          <TaggedText value={q.target_tagged} />
        </div>
      )}
      <p className="whitespace-pre-wrap text-[14px] font-medium">{q.body}</p>
      {q.replies.map((r) => (
        <div key={r.id} className="mt-2 border-l-2 border-border pl-3 text-[13.5px]">
          <div className="text-[12px] text-faint">
            {t.enumLabel(r.author_role)} · <Time iso={r.created_at} mode="relative" />
          </div>
          <p className="whitespace-pre-wrap">{r.body}</p>
        </div>
      ))}
      <form onSubmit={send} className="mt-3 space-y-2">
        <Textarea aria-label={t("app.queries.answer")} placeholder={t("app.queries.answerPlaceholder")} value={answer} onChange={(e) => setAnswer(e.target.value)} />
        <div className="flex gap-2">
          <Button type="submit" variant="primary" size="sm" loading={busy} disabled={!answer.trim()}>
            {t("app.queries.send")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void resolve()}>
            {t("app.queries.markResolved")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
