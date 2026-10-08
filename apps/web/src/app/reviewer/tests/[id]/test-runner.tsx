"use client";

import { useI18n } from "@/lib/i18n/client";
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
/** Test scores are 0..100 (community/testing.py). */
const fmtScore = (s: number) => `${(s <= 1 ? s * 100 : s).toFixed(0)} / 100`;
import { tagsOf } from "@/lib/tags";
import type { ReviewerTest, TestAttempt } from "@/lib/types";
import { formatClock, useCountdown } from "@/lib/use-countdown";

interface ItemState {
  target: string;
  errors: Annotation[];
}

export function TestRunner({ test }: { test: ReviewerTest }) {
  const { t } = useI18n();
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
      setDeadline(a.expires_at ? new Date(a.expires_at).getTime() : Date.now() + a.time_limit_min * 60_000);
    } catch (e) {
      toast.error(t("reviewer.tests.detail.testRunner.couldNotStartTheTest"), errorMessage(e));
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
        errors: (items[it.index]?.errors ?? []).map((e) => ({ span: e.excerpt, category: e.dimension, severity: e.severity })),
      }));
      setResult(await api.submitAttempt(attempt.attempt_id, answers));
      setDeadline(null);
    } catch (e) {
      submitted.current = false;
      toast.error(t("reviewer.tests.detail.testRunner.submitFailed"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, [attempt, items, toast, t]);

  // Auto-submit when time runs out.
  useEffect(() => {
    if (left !== 0 || !attempt || result) return;
    const timer = setTimeout(() => void submit(), 0);
    return () => clearTimeout(timer);
  }, [left, attempt, result, submit]);

  if (result) {
    return (
      <Card className="mx-auto max-w-lg">
        <EmptyState
          title={result.passed ? t("reviewer.tests.detail.testRunner.passed") : t("reviewer.tests.detail.testRunner.notPassedThisTime")}
          description={
            result.passed
              ? t("reviewer.tests.detail.testRunner.scoreOnceEveryTestFor", { score: fmtScore(result.score) })
              : t("reviewer.tests.detail.testRunner.scoreTheTestsListShows", { score: fmtScore(result.score) })
          }
          action={<ButtonLink href="/reviewer" variant="primary">{t("reviewer.tests.detail.testRunner.backToDashboard")}</ButtonLink>}
        />
      </Card>
    );
  }

  if (!attempt) {
    return (
      <Card className="max-w-2xl p-5">
        <h2 className="text-[15px] font-semibold">{t("reviewer.tests.detail.testRunner.beforeYouStart")}</h2>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14px] text-muted">
          <li>{t("reviewer.tests.detail.testRunner.theTimerMinutesStartsWhen", { time_limit_min: test.time_limit_min })}</li>
          <li>{t("reviewer.tests.detail.testRunner.fixEachMachineTranslationSo")}</li>
          <li>{t("reviewer.tests.detail.testRunner.selectTheFaultyTextIn")}</li>
          <li>{t("reviewer.tests.detail.testRunner.whenTimeIsUpYour")}</li>
        </ul>
        <Button variant="primary" className="mt-5" onClick={start} loading={busy} disabled={test.status !== "available"}>
          {t("reviewer.tests.detail.testRunner.startTest")}
        </Button>
        {test.status !== "available" && <p className="mt-2 text-[13px] text-muted">{t("reviewer.tests.detail.testRunner.thisTestIs", { status: test.status })}</p>}
      </Card>
    );
  }

  const low = left !== null && left < 60_000;
  return (
    <div className="space-y-4">
      <div className="sticky top-12 z-20 flex items-center gap-3 rounded-lg border border-border bg-surface/95 px-4 py-2.5 shadow-card backdrop-blur md:top-2">
        <span className="text-[13px] text-muted">
          {t("reviewer.tests.detail.testRunner.itemsErrorsMarked", { count: attempt.items.length, errors: attempt.items.reduce((n, it) => n + (items[it.index]?.errors.length ?? 0), 0) })}
        </span>
        <span
          role="timer"
          aria-live={low ? "assertive" : "off"}
          className={cn("tabular ml-auto font-mono text-[15px] font-semibold", low ? "text-danger" : "text-fg")}
        >
          {left === null ? "–" : formatClock(left)}
        </span>
        <Button variant="primary" onClick={submit} loading={busy}>
          {t("reviewer.tests.detail.testRunner.submitTest")}
        </Button>
      </div>
      {low && <Callout tone="danger">{t("reviewer.tests.detail.testRunner.lessThanAMinuteLeft")}</Callout>}
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
  const { t } = useI18n();
  const mt = useRef<AnnotatableHandle>(null);
  return (
    <Card className="p-4">
      <div className="mb-2 text-[12px] font-medium text-faint">{t("reviewer.tests.detail.testRunner.item", { value: index + 1 })}</div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3">
          <div>
            <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("reviewer.tests.detail.testRunner.source")}</div>
            <TaggedText value={source} className="text-[14.5px] leading-relaxed" />
          </div>
          <div>
            <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("reviewer.tests.detail.testRunner.machineTranslationSelectTextTo")}</div>
            <AnnotatableText ref={mt} value={original} label={t("reviewer.tests.detail.testRunner.machineTranslationForItem", { value: index + 1 })} className="rounded-md bg-subtle/60 px-3 py-2 text-[14.5px] leading-relaxed" />
          </div>
        </div>
        <div>
          <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("reviewer.tests.detail.testRunner.yourCorrectedTarget")}</div>
          <TagEditor
            value={state.target}
            onChange={(target) => onChange({ ...state, target })}
            requiredTags={tagsOf(source)}
            ariaLabel={t("reviewer.tests.detail.testRunner.correctedTargetForItem", { item: index + 1 })}
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
