"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { TagEditor, TagStatus, tagsValid, type TagEditorHandle } from "@/components/tag-editor";
import { TaggedText } from "@/components/tagged-text";
import { Badge, QeBadge, TermKindBadge, type Tone } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Callout, EmptyState, Kbd, Progress } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { ApiError, parseError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { tagsOf } from "@/lib/tags";
import type { TermKind } from "@/lib/types";
import type { AssignmentStatus, PortalSegment, PortalView } from "@/lib/vendor-types";

const STATUS_TONE: Record<AssignmentStatus, Tone> = {
  pending: "neutral",
  offered: "info",
  accepted: "accent",
  in_progress: "accent",
  delivered: "warn",
  approved: "ok",
  invoiced: "ok",
  declined: "neutral",
  expired: "neutral",
  withdrawn: "neutral",
  cancelled: "danger",
};

const CLOSED: Partial<Record<AssignmentStatus, string>> = {
  declined: k("vendor.workbench.closedDeclined"),
  expired: k("vendor.workbench.closedExpired"),
  withdrawn: k("vendor.workbench.closedWithdrawn"),
  cancelled: k("vendor.workbench.closedCancelled"),
  pending: k("vendor.workbench.closedPending"),
};

async function call<T>(token: string, path: string, init: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (init.form) body = init.form;
  else if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  const res = await fetch(`/api/vendor-portal/${encodeURIComponent(token)}${path}`, { method: init.method ?? "GET", headers, body });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

/**
 * The vendor workbench (module pm): accept or decline the offer, then review the job's
 * segments with the same tag-aware editor the reviewer cockpit uses. Every decision goes to
 * the pipeline exactly like a reviewer's. Keyboard: A accept, E edit, Ctrl+Enter submit, Esc cancel.
 */
export function Workbench({ token, initial }: { token: string; initial: PortalView }) {
  const { f, t } = useI18n();
  const toast = useToast();
  const [view, setView] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const todo = view.segments.filter((s) => !s.done);
  const [currentId, setCurrentId] = useState<string | null>(todo[0]?.id ?? null);
  const current = view.segments.find((s) => s.id === currentId) ?? todo[0] ?? null;
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState(current?.target_tagged ?? "");
  const editor = useRef<TagEditorHandle>(null);
  const a = view.assignment;
  const working = a.status === "accepted" || a.status === "in_progress";

  const fail = useCallback(
    (title: string, e: unknown) => toast.error(title, e instanceof ApiError || e instanceof Error ? e.message : String(e)),
    [toast],
  );

  async function respond(action: "accept" | "decline") {
    setBusy(action);
    try {
      const v = await call<PortalView>(token, `/${action}`, { method: "POST", body: {} });
      setView(v);
      const first = v.segments.find((s) => !s.done);
      setCurrentId(first?.id ?? null);
      setTarget(first?.target_tagged ?? "");
    } catch (e) {
      fail(t("vendor.workbench.couldNotRespond"), e);
    } finally {
      setBusy(null);
    }
  }

  const select = useCallback((s: PortalSegment | null) => {
    setCurrentId(s?.id ?? null);
    setTarget(s?.target_tagged ?? "");
    setEditing(false);
  }, []);

  const submit = useCallback(
    async (decision: "accept" | "edit") => {
      if (!current || busy) return;
      if (decision === "edit" && !(tagsValid(tagsOf(current.source_tagged), target) && target !== (current.target_tagged ?? ""))) return;
      setBusy(decision);
      try {
        await call(token, `/segments/${encodeURIComponent(current.id)}`, {
          method: "POST",
          body: { decision, target_tagged: decision === "edit" ? target : undefined },
        });
        const v = await call<PortalView>(token, "");
        setView(v);
        const next = v.segments.find((s) => !s.done && s.seq > current.seq) ?? v.segments.find((s) => !s.done) ?? null;
        select(next);
      } catch (e) {
        fail(t("vendor.workbench.couldNotSave"), e);
      } finally {
        setBusy(null);
      }
    },
    [current, busy, target, token, select, fail, t],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!working || !current || current.done) return;
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && editing) {
        e.preventDefault();
        void submit("edit");
        return;
      }
      if (e.key === "Escape" && editing) {
        e.preventDefault();
        setEditing(false);
        setTarget(current.target_tagged ?? "");
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey || editing) return;
      if (e.key.toLowerCase() === "a") {
        e.preventDefault();
        void submit("accept");
      } else if (e.key.toLowerCase() === "e") {
        e.preventDefault();
        setEditing(true);
        setTimeout(() => editor.current?.focus(), 0);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [working, current, editing, submit]);

  const done = view.segments.filter((s) => s.done).length;
  const required = current ? tagsOf(current.source_tagged) : [];
  const editValid = current ? tagsValid(required, target) && target !== (current.target_tagged ?? "") : false;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-[13.5px]">
          <span className="text-base font-semibold">
            {f.langName(view.job.source_lang)} → {f.langName(view.job.target_lang)}
          </span>
          <Badge tone={STATUS_TONE[a.status]}>{t.enumLabel(a.status)}</Badge>
          <span className="text-muted">{t.enumLabel(a.step)}</span>
          <span className="tabular text-muted">{t("vendor.workbench.words", { words: f.num(a.words) })}</span>
          {a.assignee_kind === "vendor" && (
            <span className="tabular">
              {t("vendor.workbench.fee")} <span className="font-semibold">{f.money(a.amount, a.currency)}</span>
            </span>
          )}
          {a.due_at && (
            <span className="text-muted">
              {t("vendor.workbench.due")} {f.dateTime(a.due_at)}
            </span>
          )}
          {a.po_number && (
            <AnchorButton size="sm" className="ml-auto" href={`/api/vendor-portal/${encodeURIComponent(token)}/po.pdf`} download>
              {t("vendor.workbench.purchaseOrder", { number: a.po_number })}
            </AnchorButton>
          )}
        </div>
        {a.note && <p className="border-t border-border px-4 py-2 text-[13px] text-muted">{a.note}</p>}
      </Card>

      {a.status === "offered" && (
        <Card>
          <CardHeader title={t("vendor.workbench.newOffer")} description={t("vendor.workbench.newOfferHint")} />
          <div className="flex flex-wrap items-center gap-2 px-4 py-3">
            <Button variant="primary" onClick={() => respond("accept")} loading={busy === "accept"}>
              {t("vendor.workbench.acceptOffer")}
            </Button>
            <Button onClick={() => respond("decline")} loading={busy === "decline"}>
              {t("vendor.workbench.decline")}
            </Button>
            {a.offer_expires_at && <span className="text-[13px] text-muted">{t("vendor.workbench.offerExpires", { when: f.dateTime(a.offer_expires_at) })}</span>}
          </div>
        </Card>
      )}

      {CLOSED[a.status] && (
        <Card>
          <EmptyState title={t(CLOSED[a.status] as string)} description={t("vendor.workbench.closedHint")} />
        </Card>
      )}

      {(working || a.status === "delivered" || a.status === "approved" || a.status === "invoiced") && (
        <Card className="px-4 py-3">
          <div className="flex items-center gap-3 text-[13px]">
            <Progress value={view.segments.length ? done / view.segments.length : 0} tone={view.remaining === 0 && view.segments.length > 0 ? "ok" : "accent"} />
            <span className="tabular shrink-0 text-muted">{t("vendor.workbench.progress", { done, total: view.segments.length })}</span>
          </div>
        </Card>
      )}

      {a.status === "delivered" && (
        <Callout tone="ok" title={t("vendor.workbench.deliveredTitle")}>
          {t("vendor.workbench.deliveredHint")}
        </Callout>
      )}

      {a.status === "approved" && a.assignee_kind === "vendor" && <InvoiceUpload token={token} onDone={(v) => setView(v)} />}

      {working && view.segments.length === 0 && (
        <Card>
          <EmptyState title={t("vendor.workbench.waitingForSegments")} description={t("vendor.workbench.waitingForSegmentsHint")} />
        </Card>
      )}

      {working && view.segments.length > 0 && (
        <div className="grid items-start gap-3 lg:grid-cols-[240px_minmax(0,1fr)_280px]">
          <Card className="max-h-[70vh] overflow-y-auto">
            <ol aria-label={t("vendor.workbench.segments")} className="divide-y divide-border">
              {view.segments.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => select(s)}
                    aria-current={current?.id === s.id ? "true" : undefined}
                    className={cn(
                      "flex w-full items-start gap-2 px-3 py-2 text-left text-[12.5px] hover:bg-subtle/60",
                      current?.id === s.id && "bg-accent-subtle/40",
                    )}
                  >
                    <span className={cn("tabular w-6 shrink-0 font-medium", s.done ? "text-ok" : "text-faint")}>{s.seq + 1}</span>
                    <span className={cn("line-clamp-2", s.done && "text-muted")}>{s.source_tagged.replace(/⟦[^⟧]*⟧/g, "")}</span>
                  </button>
                </li>
              ))}
            </ol>
          </Card>

          {current ? (
            <Card className="min-w-0">
              <div className="flex items-center gap-3 border-b border-border px-4 py-2.5 text-[13px]">
                <span className="font-medium">{t("vendor.workbench.segmentN", { n: current.seq + 1 })}</span>
                <span className="flex items-center gap-1.5 text-muted">
                  {t("vendor.workbench.qe")} <QeBadge value={current.qe_score} />
                </span>
                {current.done && <Badge tone="ok">{t("vendor.workbench.doneBadge")}</Badge>}
              </div>
              <div className="space-y-4 px-4 py-4">
                {current.context_before && <TaggedText value={current.context_before} className="block border-l-2 border-border pl-3 text-[13px] text-muted" />}
                <section aria-label={t("vendor.workbench.source")}>
                  <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("vendor.workbench.source")}</div>
                  <TaggedText value={current.source_tagged} className="block text-[16px] leading-relaxed" />
                </section>
                <section aria-label={t("vendor.workbench.target")}>
                  <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("vendor.workbench.target")}</div>
                  {editing ? (
                    <div className="space-y-2">
                      <TagEditor ref={editor} value={target} onChange={setTarget} requiredTags={required} ariaLabel={t("vendor.workbench.editedTarget")} className="text-[16px]" />
                      <TagStatus required={required} value={target} onInsert={(tag) => editor.current?.insertTag(tag)} />
                    </div>
                  ) : (
                    <TaggedText value={current.target_tagged} className="block rounded-md bg-accent-subtle/40 px-3 py-2 text-[16px] leading-relaxed" />
                  )}
                </section>
                {current.context_after && <TaggedText value={current.context_after} className="block border-l-2 border-border pl-3 text-[13px] text-muted" />}
              </div>
              {!current.done && (
                <div className="flex flex-wrap items-center gap-2 border-t border-border bg-subtle/40 px-4 py-3">
                  {editing ? (
                    <>
                      <Button variant="primary" onClick={() => submit("edit")} loading={busy === "edit"} disabled={!editValid}>
                        {t("vendor.workbench.submitEdit")}
                        <span className="ml-1 flex gap-0.5 opacity-80">
                          <Kbd inverse>{t("reviewer.cockpit.cockpit.ctrl")}</Kbd>
                          <Kbd inverse>↵</Kbd>
                        </span>
                      </Button>
                      <Button variant="ghost" onClick={() => select(current)}>
                        {t("vendor.workbench.cancel")} <Kbd>{t("reviewer.cockpit.cockpit.esc")}</Kbd>
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant="primary" aria-keyshortcuts="A" onClick={() => submit("accept")} loading={busy === "accept"}>
                        {t("vendor.workbench.accept")} <Kbd inverse>A</Kbd>
                      </Button>
                      <Button
                        aria-keyshortcuts="E"
                        onClick={() => {
                          setEditing(true);
                          setTimeout(() => editor.current?.focus(), 0);
                        }}
                      >
                        {t("vendor.workbench.edit")} <Kbd>E</Kbd>
                      </Button>
                    </>
                  )}
                </div>
              )}
            </Card>
          ) : (
            <Card>
              <EmptyState title={t("vendor.workbench.allDone")} description={t("vendor.workbench.allDoneHint")} />
            </Card>
          )}

          <Card>
            <div className="border-b border-border px-4 py-2.5 text-[13px] font-semibold">{t("vendor.workbench.glossary")}</div>
            {!current || current.terms.length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-muted">{t("vendor.workbench.noTerms")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {current.terms.map((term, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 px-4 py-2 text-[13px]">
                    <span>
                      <span className="font-medium">{term.source_term}</span>
                      {term.target_term && <span className="text-muted"> → {term.target_term}</span>}
                    </span>
                    {term.kind && <TermKindBadge kind={term.kind as TermKind} />}
                  </li>
                ))}
              </ul>
            )}
            <div className="border-y border-border px-4 py-2.5 text-[13px] font-semibold">{t("vendor.workbench.flagged")}</div>
            {!current || current.flagged_errors.length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-muted">{t("vendor.workbench.nothingFlagged")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {current.flagged_errors.map((e, i) => (
                  <li key={i} className="px-4 py-2 text-[13px]">
                    {typeof e === "string" ? e : `${t.enumLabel(e.severity ?? "minor")} · ${t.enumLabel(e.dimension ?? e.category ?? "issue")}${e.explanation ? `: ${e.explanation}` : ""}`}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function InvoiceUpload({ token, onDone }: { token: string; onDone: (v: PortalView) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [number, setNumber] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  async function send() {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.set("number", number.trim());
      form.set("file", file);
      await call(token, "/invoice", { method: "POST", form });
      toast.success(t("vendor.workbench.invoiceSent"));
      onDone(await call<PortalView>(token, ""));
    } catch (e) {
      toast.error(t("vendor.workbench.couldNotSendInvoice"), e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardHeader title={t("vendor.workbench.invoiceTitle")} description={t("vendor.workbench.invoiceHint")} />
      <div className="grid gap-3 p-4 sm:grid-cols-3 sm:items-end">
        <Field label={t("vendor.workbench.invoiceNumber")}>{(id) => <Input id={id} value={number} onChange={(e) => setNumber(e.target.value)} />}</Field>
        <Field label={t("vendor.workbench.invoiceFile")}>
          {(id) => <Input id={id} type="file" accept=".pdf,.png,.jpg,.jpeg,.xml,.txt,.docx,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
        </Field>
        <Button variant="primary" onClick={send} loading={busy} disabled={!number.trim() || !file}>
          {t("vendor.workbench.sendInvoice")}
        </Button>
      </div>
    </Card>
  );
}
