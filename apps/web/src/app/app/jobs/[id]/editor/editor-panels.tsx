"use client";

import { useI18n } from "@/lib/i18n/client";
import { useEffect, useState } from "react";
import { TaggedText } from "@/components/tagged-text";
import { Badge, TermKindBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { EmptyState, Kbd, Skeleton } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Job } from "@/lib/types";
import type { AssistData, ConcordanceHit, DraftCheck, MtSuggestion, SegmentComment } from "@/lib/types-workbench";

export function TmPanel({ data, canUse, onUse }: { data: AssistData | null; canUse: boolean; onUse: (v: string) => void }) {
  const { t } = useI18n();
  if (!data) return <Skeleton className="h-24" />;
  if (data.tm_matches.length === 0) return <EmptyState title={t("app.jobs.editor.noTmMatches")} description={t("app.jobs.editor.noTmMatchesHint")} />;
  return (
    <ul className="space-y-3">
      {data.tm_matches.map((m, i) => (
        <li key={m.entry_id} className="rounded-md border border-border p-2.5">
          <div className="mb-1.5 flex items-center gap-2">
            <Badge tone={m.score >= 100 ? "ok" : m.score >= 85 ? "info" : "neutral"} className="tabular">
              {Math.round(Math.min(m.score, 101))}%
            </Badge>
            <span className="text-[12px] text-faint">{m.kind}</span>
            {canUse && (
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => onUse(m.target_tagged)}>
                {t("app.jobs.editor.use")} {i < 3 && <Kbd>{`Ctrl+${i + 1}`}</Kbd>}
              </Button>
            )}
          </div>
          <p className="text-muted" aria-label={t("app.jobs.editor.matchSourceDiff")}>
            {m.diff.map((d, k) =>
              d.op === "equal" ? (
                <span key={k}>{d.text}</span>
              ) : d.op === "delete" ? (
                <del key={k} className="rounded-sm bg-danger-subtle text-danger" title={t("app.jobs.editor.onlyInMatch")}>
                  {d.text}
                </del>
              ) : (
                <ins key={k} className="rounded-sm bg-ok-subtle text-ok no-underline" title={t("app.jobs.editor.onlyInSource")}>
                  {d.text}
                </ins>
              ),
            )}
          </p>
          <p className="mt-1.5">
            <TaggedText value={m.target_tagged} />
          </p>
        </li>
      ))}
    </ul>
  );
}

export function GlossaryPanel({ data }: { data: AssistData | null }) {
  const { t } = useI18n();
  if (!data) return <Skeleton className="h-24" />;
  if (data.terms.length === 0) return <EmptyState title={t("app.jobs.editor.noTerms")} description={t("app.jobs.editor.noTermsHint")} />;
  return (
    <ul className="divide-y divide-border">
      {data.terms.map((h, i) => (
        <li key={`${h.term_id}-${i}`} className="flex items-start gap-2 py-2">
          <div className="min-w-0 flex-1">
            <div className="font-medium">{h.source_term}</div>
            <div className="text-muted">{h.kind === "do_not_translate" ? t("app.jobs.editor.keepAsIs") : (h.target_term ?? "–")}</div>
            {h.note && <div className="text-[12px] text-faint">{h.note}</div>}
          </div>
          <TermKindBadge kind={h.kind} />
        </li>
      ))}
    </ul>
  );
}

export function QaPanel({ data }: { data: DraftCheck | null }) {
  const { t } = useI18n();
  if (!data) return <Skeleton className="h-16" />;
  if (data.issues.length === 0)
    return <EmptyState title={t("app.jobs.editor.noQaIssues")} description={t("app.jobs.editor.noQaIssuesHint")} />;
  return (
    <ul className="space-y-2">
      {data.issues.map((i, k) => (
        <li key={k} className={cn("rounded-md border px-2.5 py-2", i.blocking ? "border-danger/40 bg-danger-subtle" : "border-border")}>
          <div className="flex items-center gap-2">
            <Badge tone={i.blocking ? "danger" : i.severity === "warning" ? "warn" : "neutral"}>{t.enumLabel(i.code)}</Badge>
            {i.blocking && <span className="text-[12px] font-medium text-danger">{t("app.jobs.editor.blocking")}</span>}
          </div>
          <p className="mt-1 text-muted">{i.message}</p>
        </li>
      ))}
    </ul>
  );
}

export function MtPanel({
  data,
  busy,
  allowed,
  canUse,
  onFetch,
  onUse,
}: {
  data: MtSuggestion | null;
  busy: boolean;
  allowed: boolean;
  canUse: boolean;
  onFetch: () => void;
  onUse: (v: string) => void;
}) {
  const { t } = useI18n();
  if (!allowed) return <EmptyState title={t("app.jobs.editor.mtPmOnly")} />;
  return (
    <div className="space-y-3">
      <Button size="sm" loading={busy} onClick={onFetch}>
        {t("app.jobs.editor.getMt")} <Kbd>Ctrl+M</Kbd>
      </Button>
      {data && (
        <div className="rounded-md border border-border p-2.5">
          <div className="mb-1.5 flex items-center gap-2 text-[12px] text-faint">
            {data.engine}
            {canUse && (
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => onUse(data.target_tagged)}>
                {t("app.jobs.editor.use")}
              </Button>
            )}
          </div>
          <TaggedText value={data.target_tagged} />
        </div>
      )}
      <p className="text-[12px] text-faint">{t("app.jobs.editor.mtHint")}</p>
    </div>
  );
}

export function ConcordancePanel({ job, external }: { job: Job; external: { q: string; n: number } | null }) {
  const { t } = useI18n();
  const toast = useToast();
  const [q, setQ] = useState(external?.q ?? "");
  const [side, setSide] = useState("both");
  const [hits, setHits] = useState<ConcordanceHit[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(query: string, s = side) {
    if (query.trim().length < 2) return;
    setBusy(true);
    try {
      const res = await api.concordance({ q: query.trim(), source_lang: job.source_lang, target_lang: job.target_lang, side: s });
      setHits(res.items);
    } catch (e) {
      toast.error(t("app.jobs.editor.concordanceFailed"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  // Ctrl+K with a selection runs the search for it
  useEffect(() => {
    if (!external) return;
    let live = true;
    api
      .concordance({ q: external.q, source_lang: job.source_lang, target_lang: job.target_lang, side: "both" })
      .then((res) => {
        if (!live) return;
        setQ(external.q);
        setHits(res.items);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [external, job.source_lang, job.target_lang]);

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(q);
        }}
      >
        <Input aria-label={t("app.jobs.editor.concordanceQuery")} placeholder={t("app.jobs.editor.concordanceQuery")} value={q} onChange={(e) => setQ(e.target.value)} />
        <Select
          aria-label={t("app.jobs.editor.concordanceSide")}
          className="w-28"
          value={side}
          onChange={(e) => {
            setSide(e.target.value);
            void run(q, e.target.value);
          }}
        >
          <option value="both">{t("app.jobs.editor.sideBoth")}</option>
          <option value="source">{t("app.jobs.editor.sideSource")}</option>
          <option value="target">{t("app.jobs.editor.sideTarget")}</option>
        </Select>
        <Button type="submit" size="sm" loading={busy}>
          {t("app.jobs.editor.searchTm")}
        </Button>
      </form>
      <p className="text-[12px] text-faint">
        <Kbd>Ctrl+K</Kbd> {t("app.jobs.editor.concordanceHint")}
      </p>
      {hits !== null &&
        (hits.length === 0 ? (
          <EmptyState title={t("app.jobs.editor.noConcordance")} />
        ) : (
          <ul className="divide-y divide-border">
            {hits.map((h) => (
              <li key={h.entry_id} className="space-y-1 py-2">
                <div className="text-muted">
                  <TaggedText value={h.source_tagged} />
                </div>
                <div>
                  <TaggedText value={h.target_tagged} />
                </div>
                <div className="text-[11.5px] text-faint tabular">{Math.round(h.score)}%</div>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}

export function CommentsPanel({
  job,
  segmentId,
  role,
  onCount,
}: {
  job: Job;
  segmentId: string;
  role: string;
  onCount: (threads: number) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [items, setItems] = useState<SegmentComment[] | null>(null);
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<"comment" | "query">(role === "client" ? "query" : "comment");
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [n, setN] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .comments(job.id, { segment_id: segmentId })
      .then((res) => live && setItems(res.items))
      .catch(() => live && setItems([]));
    return () => {
      live = false;
    };
  }, [job.id, segmentId, n]);

  const roots = (items ?? []).filter((c) => c.thread_id === c.id);
  const replies = (id: string) => (items ?? []).filter((c) => c.thread_id === id && c.id !== id);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    try {
      await api.addComment(job.id, replyTo ? { body, parent_id: replyTo } : { body, kind, segment_id: segmentId });
      setBody("");
      setReplyTo(null);
      if (!replyTo) onCount(roots.length + 1);
      setN((x) => x + 1);
    } catch (err) {
      toast.error(t("app.jobs.editor.commentFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function resolve(c: SegmentComment) {
    try {
      await api.resolveComment(c.id, !c.resolved);
      setN((x) => x + 1);
    } catch (err) {
      toast.error(t("app.jobs.editor.commentFailed"), errorMessage(err));
    }
  }

  if (items === null) return <Skeleton className="h-24" />;
  return (
    <div className="space-y-3">
      {roots.length === 0 && <p className="text-muted">{t("app.jobs.editor.noComments")}</p>}
      {roots.map((c) => (
        <div key={c.id} className={cn("rounded-md border p-2.5", c.kind === "query" ? "border-violet/40" : "border-border", c.resolved && "opacity-60")}>
          <div className="mb-1 flex items-center gap-2 text-[12px]">
            <Badge tone={c.kind === "query" ? "violet" : "neutral"}>
              {c.kind === "query" ? t("app.jobs.editor.queryToClient") : t("app.jobs.editor.comment")}
            </Badge>
            <span className="text-faint">{t.enumLabel(c.author_role)}</span>
            <span className="ml-auto text-faint">
              <Time iso={c.created_at} mode="relative" />
            </span>
          </div>
          <p className="whitespace-pre-wrap">{c.body}</p>
          {replies(c.id).map((r) => (
            <div key={r.id} className="mt-2 border-l-2 border-border pl-2.5">
              <div className="text-[12px] text-faint">
                {t.enumLabel(r.author_role)} · <Time iso={r.created_at} mode="relative" />
              </div>
              <p className="whitespace-pre-wrap">{r.body}</p>
            </div>
          ))}
          <div className="mt-2 flex gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => setReplyTo(c.id)}>
              {t("app.jobs.editor.reply")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void resolve(c)}>
              {c.resolved ? t("app.jobs.editor.reopen") : t("app.jobs.editor.resolve")}
            </Button>
          </div>
        </div>
      ))}
      {(role !== "client" || replyTo) && (
        <form onSubmit={submit} className="space-y-2 border-t border-border pt-3">
          {replyTo ? (
            <div className="flex items-center gap-2 text-[12px] text-muted">
              {t("app.jobs.editor.replyingToThread")}
              <Button size="sm" variant="ghost" onClick={() => setReplyTo(null)}>
                {t("app.jobs.editor.cancel")}
              </Button>
            </div>
          ) : (
            <Select aria-label={t("app.jobs.editor.commentKind")} value={kind} onChange={(e) => setKind(e.target.value as "comment" | "query")}>
              <option value="comment">{t("app.jobs.editor.internalComment")}</option>
              <option value="query">{t("app.jobs.editor.queryToClient")}</option>
            </Select>
          )}
          <Textarea
            aria-label={t("app.jobs.editor.commentBody")}
            placeholder={t("app.jobs.editor.commentPlaceholder")}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <Button type="submit" size="sm" variant="primary" loading={busy} disabled={!body.trim()}>
            {t("app.jobs.editor.post")}
          </Button>
        </form>
      )}
    </div>
  );
}
