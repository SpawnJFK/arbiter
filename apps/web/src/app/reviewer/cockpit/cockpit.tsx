"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnnotatableText, type AnnotatableHandle } from "@/components/annotatable-text";
import { ErrorAnnotator, type Annotation } from "@/components/error-annotator";
import { Icons } from "@/components/icons";
import { TagEditor, TagStatus, tagsValid, type TagEditorHandle } from "@/components/tag-editor";
import { TaggedText } from "@/components/tagged-text";
import { Badge, QeBadge, TermKindBadge } from "@/components/ui/badge";
import { Button, Spinner } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Select, Textarea } from "@/components/ui/input";
import { Callout, EmptyState, Kbd } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { tagsOf } from "@/lib/tags";
import type { FlaggedError, LangPair, Task, TaskDecision } from "@/lib/types";
import { formatClock, useCountdown } from "@/lib/use-countdown";

const DONE_LABEL: Record<TaskDecision, string> = {
  accept: k("reviewer.cockpit.done.accept"),
  edit: k("reviewer.cockpit.done.edit"),
  escalate: k("reviewer.cockpit.done.escalate"),
  skip: k("reviewer.cockpit.done.skip"),
};

type Mode = "view" | "edit" | "escalate";
type Status = "loading" | "ready" | "empty" | "error";

const SHORTCUTS: [string[], string][] = [
  [["A"], k("reviewer.cockpit.shortcut.accept")],
  [["E"], k("reviewer.cockpit.shortcut.edit")],
  [["X"], k("reviewer.cockpit.shortcut.escalate")],
  [["S"], k("reviewer.cockpit.shortcut.skip")],
  [["Ctrl", "Enter"], k("reviewer.cockpit.shortcut.submit")],
  [["Esc"], k("reviewer.cockpit.shortcut.cancel")],
  [["?"], k("reviewer.cockpit.shortcut.help")],
];

export function Cockpit({ pairs }: { pairs: LangPair[] }) {
  const { f, t } = useI18n();
  const toast = useToast();
  const [pairKey, setPairKey] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [target, setTarget] = useState("");
  const [errors, setErrors] = useState<Annotation[]>([]);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [help, setHelp] = useState(false);
  const [session, setSession] = useState({ done: 0, earned: 0 });
  const startedAt = useRef(0);
  const editor = useRef<TagEditorHandle>(null);
  const mt = useRef<AnnotatableHandle>(null);
  const commentRef = useRef<HTMLTextAreaElement>(null);
  const [deadline, setDeadline] = useState<number | null>(null);
  const left = useCountdown(deadline);
  const expired = left === 0;

  const fetchNext = useCallback(
    async (pk: string = pairKey) => {
      setStatus("loading");
      setMode("view");
      setErrors([]);
      setComment("");
      try {
        const [source_lang, target_lang] = pk ? pk.split(">") : [undefined, undefined];
        const item = await api.nextTask({ source_lang, target_lang });
        if (!item) {
          setTask(null);
          setDeadline(null);
          setStatus("empty");
          return;
        }
        setTask(item);
        setTarget(item.target_tagged ?? "");
        setDeadline(new Date(item.hold_expires_at).getTime());
        startedAt.current = performance.now();
        setStatus("ready");
      } catch (e) {
        setLoadError(errorMessage(e));
        setStatus("error");
      }
    },
    [pairKey],
  );

  // First task on mount.
  useEffect(() => {
    const timer = setTimeout(() => void fetchNext(""), 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while the queue is empty.
  useEffect(() => {
    if (status !== "empty") return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void fetchNext();
    }, 30_000);
    return () => clearInterval(timer);
  }, [status, fetchNext]);

  const required = task ? tagsOf(task.source_tagged) : [];
  const editValid = tagsValid(required, target) && target !== (task?.target_tagged ?? "");

  const submit = useCallback(
    async (decision: TaskDecision) => {
      if (!task || submitting || expired) return;
      if (decision === "edit" && !editValid) return;
      if (decision === "escalate" && !comment.trim()) {
        commentRef.current?.focus();
        return;
      }
      setSubmitting(true);
      try {
        const res = await api.submitTask(task.id, {
          decision,
          target_tagged: decision === "edit" ? target : undefined,
          errors:
            decision === "edit" && errors.length > 0
              ? errors.map(({ dimension, severity, excerpt, explanation }) => ({ dimension, severity, span: excerpt, explanation }))
              : undefined,
          comment: comment.trim() || undefined,
          time_ms: Math.round(performance.now() - startedAt.current),
        });
        const earned = Number(res.pay_amount) || 0;
        setSession((s) => ({ done: s.done + 1, earned: s.earned + earned }));
        toast.toast({
          title: t(DONE_LABEL[decision]),
          description: earned > 0 ? `+${f.money(res.pay_amount)}` : undefined,
          tone: "ok",
        });
        setSubmitting(false);
        await fetchNext();
      } catch (e) {
        setSubmitting(false);
        toast.error(t("reviewer.cockpit.cockpit.submitFailed"), errorMessage(e));
      }
    },
    [task, submitting, expired, editValid, comment, target, errors, toast, fetchNext, t, f],
  );

  const startEdit = useCallback(() => {
    setMode("edit");
    setTimeout(() => editor.current?.focus(), 0);
  }, []);

  const cancel = useCallback(() => {
    if (!task) return;
    setMode("view");
    setTarget(task.target_tagged ?? "");
    setErrors([]);
    setComment("");
  }, [task]);

  // Global keyboard shortcuts.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (help) return; // the dialog handles Esc itself
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        if (mode === "edit") {
          e.preventDefault();
          void submit("edit");
        } else if (mode === "escalate") {
          e.preventDefault();
          void submit("escalate");
        }
        return;
      }
      if (e.key === "Escape" && mode !== "view") {
        e.preventDefault();
        cancel();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "?") {
        e.preventDefault();
        setHelp(true);
        return;
      }
      if (status !== "ready" || mode !== "view") return;
      const k = e.key.toLowerCase();
      if (k === "a") {
        e.preventDefault();
        void submit("accept");
      } else if (k === "e") {
        e.preventDefault();
        startEdit();
      } else if (k === "x") {
        e.preventDefault();
        setMode("escalate");
        setTimeout(() => commentRef.current?.focus(), 0);
      } else if (k === "s") {
        e.preventDefault();
        void submit("skip");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [help, mode, status, submit, cancel, startEdit]);

  const pairSelect = pairs.length > 1 && (
    <Select
      aria-label={t("reviewer.cockpit.cockpit.languagePair")}
      value={pairKey}
      onChange={(e) => {
        setPairKey(e.target.value);
        if (status !== "ready") void fetchNext(e.target.value);
      }}
      className="w-40"
    >
      <option value="">{t("reviewer.cockpit.cockpit.allMyPairs")}</option>
      {pairs.map((p) => (
        <option key={`${p.source_lang}>${p.target_lang}`} value={`${p.source_lang}>${p.target_lang}`}>
          {p.source_lang} → {p.target_lang}
        </option>
      ))}
    </Select>
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-lg font-semibold tracking-tight">{t("reviewer.cockpit.cockpit.reviewCockpit")}</h1>
        <span className="tabular text-[12.5px] text-muted">
          {t("reviewer.cockpit.cockpit.thisSessionTask", { done: session.done })}{session.done === 1 ? "" : "s"} · {f.money(session.earned)}
        </span>
        {pairSelect}
        <Button size="sm" variant="ghost" onClick={() => setHelp(true)} aria-keyshortcuts="?">
          <Icons.keyboard className="size-4" /> {t("reviewer.cockpit.cockpit.shortcuts")} <Kbd>?</Kbd>
        </Button>
      </div>

      {status === "loading" && (
        <Card className="flex h-80 items-center justify-center gap-2 text-muted">
          <Spinner /> {t("reviewer.cockpit.cockpit.fetchingTheNextTask")}
        </Card>
      )}

      {status === "error" && (
        <Card>
          <EmptyState title={t("reviewer.cockpit.cockpit.couldNotLoadATask")} description={loadError ?? undefined} action={<Button onClick={() => fetchNext()}>{t("reviewer.cockpit.cockpit.tryAgain")}</Button>} />
        </Card>
      )}

      {status === "empty" && (
        <Card>
          <EmptyState
            icon={<Icons.check className="size-5" />}
            title={t("reviewer.cockpit.cockpit.queueEmpty")}
            description={t("reviewer.cockpit.cockpit.noTasksForYourPairs")}
            action={<Button onClick={() => fetchNext()}>{t("reviewer.cockpit.cockpit.checkNow")}</Button>}
          />
        </Card>
      )}

      {status === "ready" && task && (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Card className="min-w-0">
            {/* Task header */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2.5 text-[13px]">
              <span className="font-medium">
                {f.langName(task.source_lang)} → {f.langName(task.target_lang)}
              </span>
              <Badge>{t.enumLabel(task.domain)}</Badge>
              <span className="flex items-center gap-1.5 text-muted">
                {t("reviewer.cockpit.cockpit.qe")} <QeBadge value={task.qe_score} />
              </span>
              <span className="ml-auto flex items-center gap-4">
                <span className="text-muted">
                  {t("reviewer.cockpit.cockpit.pay")} <span className="tabular font-semibold text-fg">{f.money(task.pay_estimate)}</span>
                </span>
                <span
                  role="timer"
                  aria-label={t("reviewer.cockpit.cockpit.holdTimeLeft")}
                  className={cn(
                    "tabular rounded-md px-2 py-0.5 font-mono text-[13px] font-semibold",
                    left !== null && left < 60_000 ? "bg-danger-subtle text-danger" : "bg-subtle text-fg",
                  )}
                  title={t("reviewer.cockpit.cockpit.timeLeftOnYourHold")}
                >
                  {left === null ? "–" : formatClock(left)}
                </span>
              </span>
            </div>

            {expired && (
              <div className="px-4 pt-3">
                <Callout tone="warn" title={t("reviewer.cockpit.cockpit.holdExpired")}>
                  {t("reviewer.cockpit.cockpit.thisTaskWentBackTo")} <button className="font-medium underline" onClick={() => fetchNext()}>{t("reviewer.cockpit.cockpit.getTheNextTask")}</button>
                </Callout>
              </div>
            )}

            <div className="space-y-4 px-4 py-4">
              <Context lines={task.context_before} label={t("reviewer.cockpit.cockpit.before")} />
              <section aria-label={t("reviewer.cockpit.cockpit.source")}>
                <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("reviewer.cockpit.cockpit.source")}</div>
                <TaggedText value={task.source_tagged} className="block text-[16px] leading-relaxed" />
              </section>
              <section aria-label={t("reviewer.cockpit.cockpit.target")}>
                <div className="mb-1 flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-wide text-faint">
                  {mode === "edit" ? t("reviewer.cockpit.cockpit.machineTranslationSelectTextTo") : t("reviewer.cockpit.cockpit.target")}
                </div>
                {mode === "edit" ? (
                  <AnnotatableText ref={mt} value={task.target_tagged ?? ""} className="rounded-md bg-subtle/60 px-3 py-2 text-[16px] leading-relaxed" />
                ) : (
                  <TaggedText value={task.target_tagged} className="block rounded-md bg-accent-subtle/40 px-3 py-2 text-[16px] leading-relaxed" />
                )}
              </section>
              {mode === "edit" && (
                <section aria-label={t("reviewer.cockpit.cockpit.yourEdit")} className="space-y-2">
                  <div className="text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("reviewer.cockpit.cockpit.yourEdit")}</div>
                  <TagEditor
                    ref={editor}
                    value={target}
                    onChange={setTarget}
                    requiredTags={required}
                    ariaLabel={t("reviewer.cockpit.editedTarget")}
                    className="text-[16px]"
                  />
                  <div className="pt-1">
                    <TagStatus required={required} value={target} onInsert={(tag) => editor.current?.insertTag(tag)} />
                  </div>
                  <div className="rounded-md border border-border p-3">
                    <div className="mb-2 text-[12.5px] font-medium">{t("reviewer.cockpit.cockpit.errorAnnotation")}</div>
                    <ErrorAnnotator
                      value={errors}
                      onChange={setErrors}
                      getSpan={() => mt.current?.selectionSpan() ?? null}
                      excerptFor={(span) => (task.target_tagged ?? "").slice(span[0], span[1])}
                    />
                  </div>
                </section>
              )}
              {mode === "escalate" && (
                <section aria-label={t("reviewer.cockpit.cockpit.escalation")} className="space-y-1.5">
                  <label htmlFor="escalate-comment" className="text-[13px] font-medium">
                    {t("reviewer.cockpit.cockpit.whyEscalate")} <span className="font-normal text-muted">{t("reviewer.cockpit.cockpit.requiredGoesToThePm")}</span>
                  </label>
                  <Textarea
                    id="escalate-comment"
                    ref={commentRef}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder={t("reviewer.cockpit.cockpit.eGSourceLooksWrong")}
                  />
                </section>
              )}
              <Context lines={task.context_after} label={t("reviewer.cockpit.cockpit.after")} />
            </div>

            {/* Action bar */}
            <div className="flex flex-wrap items-center gap-2 border-t border-border bg-subtle/40 px-4 py-3">
              {mode === "view" ? (
                <>
                  <ActionButton k="A" onClick={() => submit("accept")} variant="primary" disabled={submitting || expired}>
                    {t("reviewer.cockpit.cockpit.accept")}
                  </ActionButton>
                  <ActionButton k="E" onClick={startEdit} disabled={submitting || expired}>
                    {t("reviewer.cockpit.cockpit.edit")}
                  </ActionButton>
                  <ActionButton
                    k="X"
                    onClick={() => {
                      setMode("escalate");
                      setTimeout(() => commentRef.current?.focus(), 0);
                    }}
                    disabled={submitting || expired}
                  >
                    {t("reviewer.cockpit.cockpit.escalate")}
                  </ActionButton>
                  <ActionButton k="S" onClick={() => submit("skip")} variant="ghost" disabled={submitting || expired}>
                    {t("reviewer.cockpit.cockpit.skip")}
                  </ActionButton>
                </>
              ) : (
                <>
                  <Button
                    variant="primary"
                    onClick={() => submit(mode === "edit" ? "edit" : "escalate")}
                    loading={submitting}
                    disabled={expired || (mode === "edit" ? !editValid : !comment.trim())}
                  >
                    {mode === "edit" ? t("reviewer.cockpit.cockpit.submitEdit") : t("reviewer.cockpit.cockpit.submitEscalation")}
                    <span className="ml-1 flex gap-0.5 opacity-80">
                      <Kbd inverse>{t("reviewer.cockpit.cockpit.ctrl")}</Kbd>
                      <Kbd inverse>↵</Kbd>
                    </span>
                  </Button>
                  <Button variant="ghost" onClick={cancel}>
                    {t("reviewer.cockpit.cockpit.cancel")} <Kbd>{t("reviewer.cockpit.cockpit.esc")}</Kbd>
                  </Button>
                  {mode === "edit" && !editValid && target === (task.target_tagged ?? "") && (
                    <span className="text-[12.5px] text-muted">{t("reviewer.cockpit.cockpit.changeTheTargetToSubmit")}</span>
                  )}
                </>
              )}
              {submitting && mode === "view" && <Spinner className="ml-2 text-muted" />}
            </div>
          </Card>

          {/* Sidebar */}
          <div className="space-y-3">
            <Card>
              <div className="border-b border-border px-4 py-2.5 text-[13px] font-semibold">{t("reviewer.cockpit.cockpit.glossary")}</div>
              {task.terms.length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-muted">{t("reviewer.cockpit.cockpit.noGlossaryTermsInThis")}</p>
              ) : (
                <ul className="divide-y divide-border">
                  {task.terms.map((term, i) => (
                    <li key={i} className="px-4 py-2 text-[13px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{term.source_term}</span>
                        <TermKindBadge kind={term.kind} />
                      </div>
                      <div className={cn("mt-0.5", term.kind === "forbidden" ? "text-danger" : "text-muted")}>
                        {term.kind === "do_not_translate"
                          ? t("reviewer.cockpit.cockpit.keepAsIs")
                          : term.kind === "forbidden"
                            ? term.target_term
                              ? <>{t("reviewer.cockpit.cockpit.neverUse")} <span className="line-through">{term.target_term}</span></>
                              : t("reviewer.cockpit.cockpit.mustNotAppearInThe")
                            : (term.target_term ?? "–")}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <div className="border-b border-border px-4 py-2.5 text-[13px] font-semibold">{t("reviewer.cockpit.cockpit.flaggedByTheAi")}</div>
              {task.flagged_errors.length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-muted">{t("reviewer.cockpit.cockpit.nothingFlaggedReviewItWith")}</p>
              ) : (
                <ul className="divide-y divide-border">
                  {task.flagged_errors.map((frac, i) => (
                    <FlaggedRow key={i} f={frac} />
                  ))}
                </ul>
              )}
            </Card>
            <Card className="hidden px-4 py-3 lg:block">
              <ul className="space-y-1.5 text-[12.5px] text-muted">
                {SHORTCUTS.slice(0, 6).map(([keys, label]) => (
                  <li key={label} className="flex items-center gap-2">
                    <span className="flex w-20 shrink-0 gap-1">
                      {keys.map((k) => (
                        <Kbd key={k}>{k}</Kbd>
                      ))}
                    </span>
                    {t(label)}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}

      <Dialog open={help} onClose={() => setHelp(false)} title={t("reviewer.cockpit.cockpit.keyboardShortcuts")} size="sm">
        <ul className="space-y-2 text-[13.5px]">
          {SHORTCUTS.map(([keys, label]) => (
            <li key={label} className="flex items-center gap-3">
              <span className="flex w-24 shrink-0 gap-1">
                {keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </span>
              {t(label)}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[12.5px] text-muted">{t("reviewer.cockpit.cockpit.singleKeyShortcutsAreOff")}</p>
      </Dialog>
    </div>
  );
}

function ActionButton({
  k,
  children,
  ...rest
}: { k: string; children: React.ReactNode } & React.ComponentProps<typeof Button>) {
  return (
    <Button aria-keyshortcuts={k} {...rest}>
      {children}
      <Kbd className="ml-0.5" inverse={rest.variant === "primary"}>{k}</Kbd>
    </Button>
  );
}

function Context({ lines, label }: { lines: Task["context_before"]; label: string }) {
  const { t } = useI18n();
  const list = Array.isArray(lines) ? lines : lines ? [lines] : [];
  if (list.length === 0) return null;
  return (
    <section aria-label={t("reviewer.cockpit.cockpit.context", { label })} className="border-l-2 border-border pl-3">
      <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-faint">{t("reviewer.cockpit.cockpit.context", { label })}</div>
      {list.map((l, i) => (
        <TaggedText key={i} value={l} className="block text-[13.5px] text-muted" />
      ))}
    </section>
  );
}

function FlaggedRow({ f }: { f: FlaggedError }) {
  const { t } = useI18n();
  if (typeof f === "string") return <li className="px-4 py-2 text-[13px]">{f}</li>;
  const sev = (f.severity ?? "minor").toLowerCase();
  return (
    <li className="px-4 py-2 text-[13px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={sev === "critical" ? "danger" : sev === "major" ? "warn" : "neutral"}>{t.enumLabel(sev)}</Badge>
        <span className="font-medium">{t.enumLabel(f.dimension ?? f.category ?? "issue")}</span>
        {typeof f.span === "string" && <span className="rounded bg-subtle px-1 font-mono text-[12px]">“{f.span}”</span>}
      </div>
      {(f.explanation ?? f.message) && <p className="mt-1 text-muted">{f.explanation ?? f.message}</p>}
    </li>
  );
}
