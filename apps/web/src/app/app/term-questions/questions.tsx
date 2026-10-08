"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { Glossary, TermQuestion } from "@/lib/types";

export function QuestionsList({ initial, glossaries }: { initial: TermQuestion[]; glossaries: Glossary[] }) {
  const { t } = useI18n();
  const [items, setItems] = useState(initial);
  const open = items.filter((q) => q.status !== "answered");
  const answered = items.filter((q) => q.status === "answered");

  if (items.length === 0) {
    return (
      <Card>
        <EmptyState title={t("app.termQuestions.questions.noQuestions")} description={t("app.termQuestions.questions.youWillSeeQuestionsHere")} />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {open.length === 0 && (
        <Card>
          <EmptyState title={t("app.termQuestions.questions.allCaughtUp")} description={t("app.termQuestions.questions.noOpenTermQuestions")} />
        </Card>
      )}
      {open.map((q) => (
        <QuestionCard key={q.id} q={q} glossaries={glossaries} onAnswered={(a) => setItems((xs) => xs.map((x) => (x.id === a.id ? a : x)))} />
      ))}
      {answered.length > 0 && (
        <Card>
          <div className="border-b border-border px-4 py-2.5 text-[13px] font-medium text-muted">{t("app.termQuestions.questions.answered")}</div>
          <ul className="divide-y divide-border">
            {answered.map((q) => (
              <li key={q.id} className="flex items-center gap-3 px-4 py-2.5 text-[13.5px]">
                <span className="font-medium">{q.source_term}</span>
                <span className="font-mono text-[12px] text-faint">
                  {q.source_lang} → {q.target_lang}
                </span>
                <span className="ml-auto">
                  <StatusBadge status={q.status} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function QuestionCard({ q, glossaries, onAnswered }: { q: TermQuestion; glossaries: Glossary[]; onAnswered: (q: TermQuestion) => void }) {
  const { f, t } = useI18n();
  const toast = useToast();
  const [choice, setChoice] = useState<string>(q.options[0] ?? "__custom");
  const [custom, setCustom] = useState("");
  const [glossaryId, setGlossaryId] = useState("");
  const [busy, setBusy] = useState(false);
  const answer = choice === "__custom" ? custom.trim() : choice;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!answer) return;
    setBusy(true);
    try {
      const res = await api.answerTermQuestion(q.id, { answer, add_to_glossary_id: glossaryId || undefined });
      toast.success(t("app.termQuestions.questions.answerSaved"), glossaryId ? t("app.termQuestions.questions.addedToGlossary") : undefined);
      onAnswered(res);
    } catch (err) {
      toast.error(t("app.termQuestions.questions.couldNotAnswer"), errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit}>
        <fieldset className="p-4">
          <legend className="sr-only">{t("app.termQuestions.questions.howShouldBeTranslated", { source_term: q.source_term })}</legend>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold">{q.source_term}</span>
            <span className="text-[13px] text-muted">
              {f.langName(q.source_lang)} → {f.langName(q.target_lang)}
            </span>
            <span className="ml-auto">
              <StatusBadge status={q.status} />
            </span>
          </div>
          <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
            {q.options.map((o) => (
              <label key={o} className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-[13.5px] ${choice === o ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover"}`}>
                <input type="radio" name={`q-${q.id}`} className="accent-[var(--accent)]" checked={choice === o} onChange={() => setChoice(o)} />
                {o}
              </label>
            ))}
            <label className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-[13.5px] ${choice === "__custom" ? "border-accent bg-accent-subtle/50" : "border-border"}`}>
              <input type="radio" name={`q-${q.id}`} className="accent-[var(--accent)]" checked={choice === "__custom"} onChange={() => setChoice("__custom")} />
              <Input
                aria-label={t("app.termQuestions.questions.otherTranslation")}
                placeholder={t("app.termQuestions.questions.other")}
                value={custom}
                onFocus={() => setChoice("__custom")}
                onChange={(e) => setCustom(e.target.value)}
                className="h-7 border-0 px-1 shadow-none"
              />
            </label>
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-subtle/40 px-4 py-2.5">
          <Select aria-label={t("app.termQuestions.questions.addToGlossary")} value={glossaryId} onChange={(e) => setGlossaryId(e.target.value)} className="w-64">
            <option value="">{t("app.termQuestions.questions.doNotAddToA")}</option>
            {glossaries.map((g) => (
              <option key={g.id} value={g.id}>
                {t("app.termQuestions.questions.addTo", { name: g.name })}
              </option>
            ))}
          </Select>
          <Button type="submit" variant="primary" className="ml-auto" loading={busy} disabled={!answer}>
            {t("app.termQuestions.questions.answer")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
