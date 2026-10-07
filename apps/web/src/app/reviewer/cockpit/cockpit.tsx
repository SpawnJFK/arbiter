"use client";

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
import { humanize, langName, money } from "@/lib/format";
import { tagsOf } from "@/lib/tags";
import type { FlaggedError, LangPair, Task, TaskDecision } from "@/lib/types";
import { formatClock, useCountdown } from "@/lib/use-countdown";

const DONE_LABEL: Record<TaskDecision, string> = {
  accept: "Accepted",
  edit: "Edit submitted",
  escalate: "Escalated",
  skip: "Skipped",
};

type Mode = "view" | "edit" | "escalate";
type Status = "loading" | "ready" | "empty" | "error";

const SHORTCUTS: [string[], string][] = [
  [["A"], "Accept the translation as is"],
  [["E"], "Edit the target (focuses the editor)"],
  [["X"], "Escalate (needs a comment)"],
  [["S"], "Skip this task"],
  [["Ctrl", "Enter"], "Submit edit or escalation (Cmd+Enter on Mac)"],
  [["Esc"], "Cancel edit or escalation"],
  [["?"], "Show this help"],
];

export function Cockpit({ pairs }: { pairs: LangPair[] }) {
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
        const t = await api.nextTask({ source_lang, target_lang });
        if (!t) {
          setTask(null);
          setDeadline(null);
          setStatus("empty");
          return;
        }
        setTask(t);
        setTarget(t.target_tagged);
        setDeadline(new Date(t.hold_expires_at).getTime());
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
    const t = setTimeout(() => void fetchNext(""), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while the queue is empty.
  useEffect(() => {
    if (status !== "empty") return;
    const t = setInterval(() => {
      if (document.visibilityState === "visible") void fetchNext();
    }, 30_000);
    return () => clearInterval(t);
  }, [status, fetchNext]);

  const required = task ? tagsOf(task.source_tagged) : [];
  const editValid = tagsValid(required, target) && target !== task?.target_tagged;

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
              ? errors.map(({ dimension, severity, span, explanation }) => ({ dimension, severity, span, explanation }))
              : undefined,
          comment: comment.trim() || undefined,
          time_ms: Math.round(performance.now() - startedAt.current),
        });
        const earned = Number(res.pay_amount) || 0;
        setSession((s) => ({ done: s.done + 1, earned: s.earned + earned }));
        toast.toast({
          title: DONE_LABEL[decision],
          description: earned > 0 ? `+${money(res.pay_amount)}` : undefined,
          tone: "ok",
        });
        setSubmitting(false);
        await fetchNext();
      } catch (e) {
        setSubmitting(false);
        toast.error("Submit failed", errorMessage(e));
      }
    },
    [task, submitting, expired, editValid, comment, target, errors, toast, fetchNext],
  );

  const startEdit = useCallback(() => {
    setMode("edit");
    setTimeout(() => editor.current?.focus(), 0);
  }, []);

  const cancel = useCallback(() => {
    if (!task) return;
    setMode("view");
    setTarget(task.target_tagged);
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
      aria-label="Language pair"
      value={pairKey}
      onChange={(e) => {
        setPairKey(e.target.value);
        if (status !== "ready") void fetchNext(e.target.value);
      }}
      className="w-40"
    >
      <option value="">All my pairs</option>
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
        <h1 className="mr-auto text-lg font-semibold tracking-tight">Review cockpit</h1>
        <span className="tabular text-[12.5px] text-muted">
          This session: {session.done} task{session.done === 1 ? "" : "s"} · {money(session.earned)}
        </span>
        {pairSelect}
        <Button size="sm" variant="ghost" onClick={() => setHelp(true)} aria-keyshortcuts="?">
          <Icons.keyboard className="size-4" /> Shortcuts <Kbd>?</Kbd>
        </Button>
      </div>

      {status === "loading" && (
        <Card className="flex h-80 items-center justify-center gap-2 text-muted">
          <Spinner /> Fetching the next task…
        </Card>
      )}

      {status === "error" && (
        <Card>
          <EmptyState title="Could not load a task" description={loadError ?? undefined} action={<Button onClick={() => fetchNext()}>Try again</Button>} />
        </Card>
      )}

      {status === "empty" && (
        <Card>
          <EmptyState
            icon={<Icons.check className="size-5" />}
            title="Queue empty"
            description="No tasks for your pairs right now. We check again every 30 seconds while this page is open."
            action={<Button onClick={() => fetchNext()}>Check now</Button>}
          />
        </Card>
      )}

      {status === "ready" && task && (
        <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Card className="min-w-0">
            {/* Task header */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-2.5 text-[13px]">
              <span className="font-medium">
                {langName(task.source_lang)} → {langName(task.target_lang)}
              </span>
              <Badge>{humanize(task.domain)}</Badge>
              <span className="flex items-center gap-1.5 text-muted">
                QE <QeBadge value={task.qe_score} />
              </span>
              <span className="ml-auto flex items-center gap-4">
                <span className="text-muted">
                  Pay <span className="tabular font-semibold text-fg">{money(task.pay_estimate)}</span>
                </span>
                <span
                  role="timer"
                  aria-label="Hold time left"
                  className={cn(
                    "tabular rounded-md px-2 py-0.5 font-mono text-[13px] font-semibold",
                    left !== null && left < 60_000 ? "bg-danger-subtle text-danger" : "bg-subtle text-fg",
                  )}
                  title="Time left on your hold for this task"
                >
                  {left === null ? "–" : formatClock(left)}
                </span>
              </span>
            </div>

            {expired && (
              <div className="px-4 pt-3">
                <Callout tone="warn" title="Hold expired">
                  This task went back to the queue. <button className="font-medium underline" onClick={() => fetchNext()}>Get the next task</button>
                </Callout>
              </div>
            )}

            <div className="space-y-4 px-4 py-4">
              <Context lines={task.context_before} label="Before" />
              <section aria-label="Source">
                <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">Source</div>
                <TaggedText value={task.source_tagged} className="block text-[16px] leading-relaxed" />
              </section>
              <section aria-label="Target">
                <div className="mb-1 flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-wide text-faint">
                  {mode === "edit" ? "Machine translation (select text to mark errors)" : "Target"}
                </div>
                {mode === "edit" ? (
                  <AnnotatableText ref={mt} value={task.target_tagged} className="rounded-md bg-subtle/60 px-3 py-2 text-[16px] leading-relaxed" />
                ) : (
                  <TaggedText value={task.target_tagged} className="block rounded-md bg-accent-subtle/40 px-3 py-2 text-[16px] leading-relaxed" />
                )}
              </section>
              {mode === "edit" && (
                <section aria-label="Your edit" className="space-y-2">
                  <div className="text-[11.5px] font-medium uppercase tracking-wide text-faint">Your edit</div>
                  <TagEditor
                    ref={editor}
                    value={target}
                    onChange={setTarget}
                    requiredTags={required}
                    ariaLabel="Edited target"
                    className="text-[16px]"
                  />
                  <div className="pt-1">
                    <TagStatus required={required} value={target} onInsert={(t) => editor.current?.insertTag(t)} />
                  </div>
                  <div className="rounded-md border border-border p-3">
                    <div className="mb-2 text-[12.5px] font-medium">Error annotation</div>
                    <ErrorAnnotator
                      value={errors}
                      onChange={setErrors}
                      getSpan={() => mt.current?.selectionSpan() ?? null}
                      excerptFor={(span) => task.target_tagged.slice(span[0], span[1])}
                    />
                  </div>
                </section>
              )}
              {mode === "escalate" && (
                <section aria-label="Escalation" className="space-y-1.5">
                  <label htmlFor="escalate-comment" className="text-[13px] font-medium">
                    Why escalate? <span className="font-normal text-muted">(required, goes to the PM)</span>
                  </label>
                  <Textarea
                    id="escalate-comment"
                    ref={commentRef}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="e.g. Source looks wrong: 0.5 mL/h may be a typo for 5 mL/h. Please confirm with the author."
                  />
                </section>
              )}
              <Context lines={task.context_after} label="After" />
            </div>

            {/* Action bar */}
            <div className="flex flex-wrap items-center gap-2 border-t border-border bg-subtle/40 px-4 py-3">
              {mode === "view" ? (
                <>
                  <ActionButton k="A" onClick={() => submit("accept")} variant="primary" disabled={submitting || expired}>
                    Accept
                  </ActionButton>
                  <ActionButton k="E" onClick={startEdit} disabled={submitting || expired}>
                    Edit
                  </ActionButton>
                  <ActionButton
                    k="X"
                    onClick={() => {
                      setMode("escalate");
                      setTimeout(() => commentRef.current?.focus(), 0);
                    }}
                    disabled={submitting || expired}
                  >
                    Escalate
                  </ActionButton>
                  <ActionButton k="S" onClick={() => submit("skip")} variant="ghost" disabled={submitting || expired}>
                    Skip
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
                    {mode === "edit" ? "Submit edit" : "Submit escalation"}
                    <span className="ml-1 flex gap-0.5 opacity-80">
                      <Kbd inverse>Ctrl</Kbd>
                      <Kbd inverse>↵</Kbd>
                    </span>
                  </Button>
                  <Button variant="ghost" onClick={cancel}>
                    Cancel <Kbd>Esc</Kbd>
                  </Button>
                  {mode === "edit" && !editValid && target === task.target_tagged && (
                    <span className="text-[12.5px] text-muted">Change the target to submit an edit, or cancel and accept.</span>
                  )}
                </>
              )}
              {submitting && mode === "view" && <Spinner className="ml-2 text-muted" />}
            </div>
          </Card>

          {/* Sidebar */}
          <div className="space-y-3">
            <Card>
              <div className="border-b border-border px-4 py-2.5 text-[13px] font-semibold">Glossary</div>
              {task.terms.length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-muted">No glossary terms in this segment.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {task.terms.map((t, i) => (
                    <li key={i} className="px-4 py-2 text-[13px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{t.source_term}</span>
                        <TermKindBadge kind={t.kind} />
                      </div>
                      <div className={cn("mt-0.5", t.kind === "forbidden" ? "text-danger" : "text-muted")}>
                        {t.kind === "do_not_translate"
                          ? "Keep as is"
                          : t.kind === "forbidden"
                            ? t.target_term
                              ? <>Never use <span className="line-through">{t.target_term}</span></>
                              : "Must not appear in the target"
                            : (t.target_term ?? "–")}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <div className="border-b border-border px-4 py-2.5 text-[13px] font-semibold">Flagged by the AI</div>
              {task.flagged_errors.length === 0 ? (
                <p className="px-4 py-3 text-[13px] text-muted">Nothing flagged. Review it with fresh eyes anyway.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {task.flagged_errors.map((f, i) => (
                    <FlaggedRow key={i} f={f} />
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
                    {label}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}

      <Dialog open={help} onClose={() => setHelp(false)} title="Keyboard shortcuts" size="sm">
        <ul className="space-y-2 text-[13.5px]">
          {SHORTCUTS.map(([keys, label]) => (
            <li key={label} className="flex items-center gap-3">
              <span className="flex w-24 shrink-0 gap-1">
                {keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </span>
              {label}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[12.5px] text-muted">Single-key shortcuts are off while you type in the editor or a text field.</p>
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
  const list = Array.isArray(lines) ? lines : lines ? [lines] : [];
  if (list.length === 0) return null;
  return (
    <section aria-label={`Context ${label.toLowerCase()}`} className="border-l-2 border-border pl-3">
      <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-faint">Context {label.toLowerCase()}</div>
      {list.map((l, i) => (
        <TaggedText key={i} value={l} className="block text-[13.5px] text-muted" />
      ))}
    </section>
  );
}

function FlaggedRow({ f }: { f: FlaggedError }) {
  if (typeof f === "string") return <li className="px-4 py-2 text-[13px]">{f}</li>;
  const sev = (f.severity ?? "minor").toLowerCase();
  return (
    <li className="px-4 py-2 text-[13px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={sev === "critical" ? "danger" : sev === "major" ? "warn" : "neutral"}>{humanize(sev)}</Badge>
        <span className="font-medium">{humanize(f.dimension ?? f.category ?? "issue")}</span>
        {typeof f.span === "string" && <span className="rounded bg-subtle px-1 font-mono text-[12px]">“{f.span}”</span>}
      </div>
      {(f.explanation ?? f.message) && <p className="mt-1 text-muted">{f.explanation ?? f.message}</p>}
    </li>
  );
}
