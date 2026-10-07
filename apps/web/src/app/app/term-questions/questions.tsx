"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { langName } from "@/lib/format";
import type { Glossary, TermQuestion } from "@/lib/types";

export function QuestionsList({ initial, glossaries }: { initial: TermQuestion[]; glossaries: Glossary[] }) {
  const [items, setItems] = useState(initial);
  const open = items.filter((q) => q.status !== "answered");
  const answered = items.filter((q) => q.status === "answered");

  if (items.length === 0) {
    return (
      <Card>
        <EmptyState title="No questions" description="You will see questions here when a reviewer needs a terminology decision." />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {open.length === 0 && (
        <Card>
          <EmptyState title="All caught up" description="No open term questions." />
        </Card>
      )}
      {open.map((q) => (
        <QuestionCard key={q.id} q={q} glossaries={glossaries} onAnswered={(a) => setItems((xs) => xs.map((x) => (x.id === a.id ? a : x)))} />
      ))}
      {answered.length > 0 && (
        <Card>
          <div className="border-b border-border px-4 py-2.5 text-[13px] font-medium text-muted">Answered</div>
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
      toast.success("Answer saved", glossaryId ? "Added to the glossary as a mandatory term." : undefined);
      onAnswered(res);
    } catch (err) {
      toast.error("Could not answer", errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit}>
        <fieldset className="p-4">
          <legend className="sr-only">How should “{q.source_term}” be translated?</legend>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold">{q.source_term}</span>
            <span className="text-[13px] text-muted">
              {langName(q.source_lang)} → {langName(q.target_lang)}
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
                aria-label="Other translation"
                placeholder="Other…"
                value={custom}
                onFocus={() => setChoice("__custom")}
                onChange={(e) => setCustom(e.target.value)}
                className="h-7 border-0 px-1 shadow-none"
              />
            </label>
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-subtle/40 px-4 py-2.5">
          <Select aria-label="Add to glossary" value={glossaryId} onChange={(e) => setGlossaryId(e.target.value)} className="w-64">
            <option value="">Do not add to a glossary</option>
            {glossaries.map((g) => (
              <option key={g.id} value={g.id}>
                Add to: {g.name}
              </option>
            ))}
          </Select>
          <Button type="submit" variant="primary" className="ml-auto" loading={busy} disabled={!answer}>
            Answer
          </Button>
        </div>
      </form>
    </Card>
  );
}
