"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnnotatableText, type AnnotatableHandle } from "@/components/annotatable-text";
import { ErrorAnnotator, type Annotation } from "@/components/error-annotator";
import { TagEditor } from "@/components/tag-editor";
import { TaggedText } from "@/components/tagged-text";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Callout, EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { pct } from "@/lib/format";
import { tagsOf } from "@/lib/tags";
import type { ReviewerTest, TestAttempt } from "@/lib/types";
import { formatClock, useCountdown } from "@/lib/use-countdown";

interface ItemState {
  target: string;
  errors: Annotation[];
}

export function TestRunner({ test }: { test: ReviewerTest }) {
  const toast = useToast();
  const [attempt, setAttempt] = useState<TestAttempt | null>(null);
  const [deadline, setDeadline] = useState<number | null>(null);
  const [items, setItems] = useState<Record<number, ItemState>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ score: number; passed: boolean } | null>(null);
  const left = useCountdown(deadline);
  const submitted = useRef(false);

  async function start() {
    setBusy(true);
    try {
      const a = await api.startTest(test.id);
      setAttempt(a);
      setItems(Object.fromEntries(a.items.map((it) => [it.index, { target: it.target, errors: [] }])));
      setDeadline(Date.now() + a.time_limit_min * 60_000);
    } catch (e) {
      toast.error("Could not start the test", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const submit = useCallback(async () => {
    if (!attempt || submitted.current) return;
    submitted.current = true;
    setBusy(true);
    try {
      const answers = attempt.items.map((it) => ({
        index: it.index,
        target: items[it.index]?.target ?? it.target,
        errors: (items[it.index]?.errors ?? []).map((e) => ({ span: e.span, category: e.dimension, severity: e.severity })),
      }));
      setResult(await api.submitAttempt(attempt.attempt_id, answers));
      setDeadline(null);
    } catch (e) {
      submitted.current = false;
      toast.error("Submit failed", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, [attempt, items, toast]);

  // Auto-submit when time runs out.
  useEffect(() => {
    if (left !== 0 || !attempt || result) return;
    const t = setTimeout(() => void submit(), 0);
    return () => clearTimeout(t);
  }, [left, attempt, result, submit]);

  if (result) {
    return (
      <Card className="mx-auto max-w-lg">
        <EmptyState
          title={result.passed ? "Passed" : "Not passed this time"}
          description={
            result.passed
              ? `Score ${pct(result.score)}. The pair is now active; tasks will start arriving in the cockpit.`
              : `Score ${pct(result.score)}. The tests list shows when you can retake it.`
          }
          action={<ButtonLink href="/reviewer" variant="primary">Back to dashboard</ButtonLink>}
        />
      </Card>
    );
  }

  if (!attempt) {
    return (
      <Card className="max-w-2xl p-5">
        <h2 className="text-[15px] font-semibold">Before you start</h2>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14px] text-muted">
          <li>The timer ({test.time_limit_min} minutes) starts when you click Start.</li>
          <li>Fix each machine translation so it is correct and fluent. Inline tags must stay in place.</li>
          <li>Select the faulty text in the target and mark it with a dimension and severity (minor, major, critical).</li>
          <li>When time is up, your answers are submitted automatically.</li>
        </ul>
        <Button variant="primary" className="mt-5" onClick={start} loading={busy} disabled={test.status !== "available"}>
          Start test
        </Button>
        {test.status !== "available" && <p className="mt-2 text-[13px] text-muted">This test is {test.status}.</p>}
      </Card>
    );
  }

  const low = left !== null && left < 60_000;
  return (
    <div className="space-y-4">
      <div className="sticky top-12 z-20 flex items-center gap-3 rounded-lg border border-border bg-surface/95 px-4 py-2.5 shadow-card backdrop-blur md:top-2">
        <span className="text-[13px] text-muted">
          {attempt.items.length} items · {attempt.items.reduce((n, it) => n + (items[it.index]?.errors.length ?? 0), 0)} errors marked
        </span>
        <span
          role="timer"
          aria-live={low ? "assertive" : "off"}
          className={cn("tabular ml-auto font-mono text-[15px] font-semibold", low ? "text-danger" : "text-fg")}
        >
          {left === null ? "–" : formatClock(left)}
        </span>
        <Button variant="primary" onClick={submit} loading={busy}>
          Submit test
        </Button>
      </div>
      {low && <Callout tone="danger">Less than a minute left. Answers are submitted automatically at 0:00.</Callout>}
      {attempt.items.map((it) => (
        <TestItem
          key={it.index}
          index={it.index}
          source={it.source}
          original={it.target}
          state={items[it.index] ?? { target: it.target, errors: [] }}
          onChange={(s) => setItems((x) => ({ ...x, [it.index]: s }))}
        />
      ))}
    </div>
  );
}

function TestItem({
  index,
  source,
  original,
  state,
  onChange,
}: {
  index: number;
  source: string;
  original: string;
  state: ItemState;
  onChange: (s: ItemState) => void;
}) {
  const mt = useRef<AnnotatableHandle>(null);
  return (
    <Card className="p-4">
      <div className="mb-2 text-[12px] font-medium text-faint">Item {index + 1}</div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3">
          <div>
            <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">Source</div>
            <TaggedText value={source} className="text-[14.5px] leading-relaxed" />
          </div>
          <div>
            <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">Machine translation (select text to mark errors)</div>
            <AnnotatableText ref={mt} value={original} label={`Machine translation for item ${index + 1}`} className="rounded-md bg-subtle/60 px-3 py-2 text-[14.5px] leading-relaxed" />
          </div>
        </div>
        <div>
          <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">Your corrected target</div>
          <TagEditor
            value={state.target}
            onChange={(target) => onChange({ ...state, target })}
            requiredTags={tagsOf(source)}
            ariaLabel={`Corrected target for item ${index + 1}`}
          />
        </div>
      </div>
      <div className="mt-3 border-t border-border pt-3">
        <ErrorAnnotator
          compact
          value={state.errors}
          onChange={(errors) => onChange({ ...state, errors })}
          getSpan={() => mt.current?.selectionSpan() ?? null}
          excerptFor={(span) => original.slice(span[0], span[1])}
        />
      </div>
    </Card>
  );
}
