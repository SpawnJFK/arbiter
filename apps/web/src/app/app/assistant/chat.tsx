"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button, Spinner } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Kbd } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ApplyResult, AssistantMessage, AssistantThread, PlanAction } from "@/lib/types";

const EXAMPLES = [
  {
    label: "Set up an agency (Serbian)",
    text: "Mi smo agencija Lingua Pro. Naši klijenti su Acme d.o.o., Beta Pharma i Gamma Soft. Workflow: MT, pa QE, pa revizija, pa druga revizija za farmaciju, i odobrenje klijenta. Cena 0.08 EUR po reči. Hoću dashboard sa prihodom, maržom i poslovima koji kasne.",
  },
  {
    label: "Set up a software localization team",
    text: "We are Northwind Localization. Our clients are Fabrikam and Contoso. Workflow: MT, then QE, then review. Price 0.06 EUR per word. I want a dashboard with revenue, margin and overdue jobs.",
  },
  { label: "Ask about the business", text: "Which jobs are overdue right now, and what is our margin this month?" },
];

const ACTION_ICON: Record<string, keyof typeof Icons> = {
  create_workflow: "flow",
  create_price_list: "tag",
  create_account: "building",
  create_contact: "users",
  create_deal: "kanban",
  create_activity: "checklist",
  create_dashboard: "grid",
  update_org: "gear",
  create_glossary: "book",
  add_terms: "book",
  create_webhook: "hook",
};

function linkFor(type: string, id?: string | null): string | null {
  switch (type) {
    case "create_workflow":
      return id ? `/app/workflows/${id}` : "/app/workflows";
    case "create_price_list":
      return id ? `/app/price-lists/${id}` : "/app/price-lists";
    case "create_account":
      return id ? `/app/crm/${id}` : "/app/crm";
    case "create_deal":
      return "/app/crm/deals";
    case "create_activity":
      return "/app/crm/tasks";
    case "create_contact":
      return "/app/crm";
    case "create_dashboard":
      return "/app";
    case "update_org":
      return "/app/settings";
    case "create_glossary":
    case "add_terms":
      return id ? `/app/glossaries/${id}` : "/app/glossaries";
    case "create_webhook":
      return "/app/settings/webhooks";
    default:
      return null;
  }
}

export function AssistantChat({ threads, thread }: { threads: AssistantThread[]; thread: AssistantThread | null }) {
  const router = useRouter();
  const toast = useToast();
  const [messages, setMessages] = useState<AssistantMessage[]>(thread?.messages ?? []);
  const [threadId, setThreadId] = useState(thread?.id ?? null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  // Follow navigation between threads (sidebar, "New conversation") without remounting, so a
  // response or an apply in flight is never lost when the URL gains ?thread= after a first message.
  const [shownThread, setShownThread] = useState(thread?.id ?? null);
  if ((thread?.id ?? null) !== shownThread) {
    setShownThread(thread?.id ?? null);
    if ((thread?.id ?? null) !== threadId) {
      setThreadId(thread?.id ?? null);
      setMessages(thread?.messages ?? []);
    }
  }
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, sending]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || sending) return;
    setSending(true);
    setDraft("");
    const optimistic: AssistantMessage = { id: `local-${Date.now()}`, role: "user", content, plan: null, applied: [], created_at: new Date().toISOString() };
    setMessages((m) => [...m, optimistic]);
    try {
      let id = threadId;
      if (!id) {
        const t = await api.createThread(content.slice(0, 60));
        id = t.id;
        setThreadId(id);
      }
      const res = await api.sendMessage(id, content);
      setMessages((m) => [...m.filter((x) => x.id !== optimistic.id), res.user_message, res.assistant_message]);
      if (!threadId) router.replace(`/app/assistant?thread=${id}`, { scroll: false });
      router.refresh();
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== optimistic.id));
      setDraft(content);
      toast.error("The assistant could not answer", errorMessage(e));
    } finally {
      setSending(false);
      input.current?.focus();
    }
  }

  return (
    <div className="-my-2 grid h-[calc(100dvh-7rem)] min-h-[520px] gap-4 lg:grid-cols-[240px_1fr]">
      <aside className="hidden flex-col overflow-hidden rounded-lg border border-border bg-surface lg:flex" aria-label="Conversations">
        <div className="border-b border-border p-2">
          <Button
            className="w-full"
            onClick={() => {
              router.push("/app/assistant");
            }}
          >
            <Icons.plus className="size-3.5" /> New conversation
          </Button>
        </div>
        <ul className="flex-1 overflow-y-auto p-1.5">
          {threads.length === 0 && <li className="px-2 py-3 text-[12.5px] text-faint">No conversations yet.</li>}
          {threads.map((t) => (
            <li key={t.id}>
              <Link
                href={`/app/assistant?thread=${t.id}`}
                aria-current={t.id === threadId ? "page" : undefined}
                className={cn("block rounded-md px-2 py-1.5 text-[13px]", t.id === threadId ? "bg-hover font-medium" : "text-muted hover:bg-hover hover:text-fg")}
              >
                <span className="line-clamp-2">{t.title || "Untitled"}</span>
                <span className="mt-0.5 block text-[11.5px] text-faint">
                  <Time iso={t.updated_at ?? t.created_at} mode="relative" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface" aria-label="Assistant conversation">
        <header className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <Icons.sparkle className="size-4 text-accent" />
          <h1 className="text-[14px] font-semibold">Workspace assistant</h1>
          <span className="ml-auto hidden text-[12px] text-muted sm:block">Proposes changes as a plan. Nothing changes until you apply it.</span>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
          {messages.length === 0 ? (
            <div className="mx-auto max-w-2xl py-6">
              <h2 className="text-lg font-semibold tracking-tight">Describe your agency in plain language</h2>
              <p className="mt-1 text-[14px] text-muted">
                Clients, how work should flow, what you charge, what you want to see. The assistant answers with a plan: accounts, workflows, price lists and dashboards it would create. You review every action and apply all of it, some of it, or none.
              </p>
              <div className="mt-5 space-y-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex.label}
                    type="button"
                    onClick={() => {
                      setDraft(ex.text);
                      input.current?.focus();
                    }}
                    className="block w-full rounded-lg border border-border bg-bg px-3.5 py-2.5 text-left transition-colors hover:border-accent/50 hover:bg-accent-subtle/30"
                  >
                    <span className="text-[12px] font-medium text-accent">{ex.label}</span>
                    <span className="mt-0.5 line-clamp-2 block text-[13.5px] text-fg/90">{ex.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <ol className="mx-auto max-w-3xl space-y-4">
              {messages.map((m) => (
                <li key={m.id}>{m.role === "user" ? <UserBubble m={m} /> : <AssistantBubble m={m} onUpdate={(u) => setMessages((xs) => xs.map((x) => (x.id === u.id ? u : x)))} />}</li>
              ))}
              {sending && (
                <li className="flex items-center gap-2 text-[13px] text-muted">
                  <Spinner /> Thinking…
                </li>
              )}
            </ol>
          )}
          <div ref={bottom} />
        </div>
        <form
          className="border-t border-border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send(draft);
          }}
        >
          <div className="flex items-end gap-2 rounded-lg border border-border-strong bg-surface p-1.5 shadow-card focus-within:outline-2 focus-within:outline-ring">
            <label htmlFor="assistant-input" className="sr-only">
              Message the assistant
            </label>
            <textarea
              id="assistant-input"
              ref={input}
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send(draft);
                }
              }}
              placeholder="Describe your agency, or ask about jobs, revenue and deals…"
              className="max-h-48 min-h-11 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px] outline-none placeholder:text-faint"
            />
            <Button type="submit" variant="primary" disabled={!draft.trim() || sending} aria-label="Send">
              <Icons.send className="size-4" />
            </Button>
          </div>
          <p className="mt-1.5 flex items-center gap-1 text-[11.5px] text-faint">
            <Kbd>Enter</Kbd> send · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> new line
          </p>
        </form>
      </section>
    </div>
  );
}

function UserBubble({ m }: { m: AssistantMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[14px] text-accent-fg">{m.content}</div>
    </div>
  );
}

function AssistantBubble({ m, onUpdate }: { m: AssistantMessage; onUpdate: (m: AssistantMessage) => void }) {
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-accent">
        <Icons.sparkle className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="whitespace-pre-wrap text-[14px] leading-relaxed">{m.content}</div>
        {m.plan && m.plan.length > 0 && <PlanCard m={m} onUpdate={onUpdate} />}
      </div>
    </div>
  );
}

function PlanCard({ m, onUpdate }: { m: AssistantMessage; onUpdate: (m: AssistantMessage) => void }) {
  const router = useRouter();
  const toast = useToast();
  const plan = m.plan as PlanAction[];
  const applied = new Set(m.applied);
  const [selected, setSelected] = useState<Set<number>>(() => new Set(plan.map((_, i) => i).filter((i) => !applied.has(i))));
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [results, setResults] = useState<Record<number, ApplyResult>>(() =>
    Object.fromEntries(Object.entries(m.results ?? {}).map(([k, v]) => [Number(k), { index: Number(k), type: plan[Number(k)]?.type ?? "", ok: true, id: v.id }])),
  );
  const [busy, setBusy] = useState(false);
  const pending = plan.map((_, i) => i).filter((i) => !applied.has(i));

  async function apply(indices?: number[]) {
    setBusy(true);
    try {
      const res = await api.applyPlan(m.id, indices);
      const map = { ...results };
      for (const r of res.results) map[r.index] = r;
      setResults(map);
      const okCount = res.results.filter((r) => r.ok && !r.skipped).length;
      const failed = res.results.filter((r) => !r.ok).length;
      const nextApplied = res.message?.applied ?? [...new Set([...m.applied, ...res.results.filter((r) => r.ok).map((r) => r.index)])];
      onUpdate({ ...m, ...(res.message ?? {}), applied: nextApplied });
      setSelected(new Set());
      if (failed) toast.error(`${okCount} applied, ${failed} failed`, "See the messages next to the actions.");
      else toast.success(`${okCount} action${okCount === 1 ? "" : "s"} applied`);
      router.refresh();
    } catch (e) {
      toast.error("Could not apply the plan", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-3 overflow-hidden" role="group" aria-label="Proposed plan">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-subtle/50 px-3.5 py-2">
        <span className="text-[13px] font-semibold">Proposed plan</span>
        <Badge>{plan.length} actions</Badge>
        {pending.length === 0 ? <Badge tone="ok">All applied</Badge> : m.applied.length > 0 ? <Badge tone="accent">{m.applied.length} applied</Badge> : <Badge tone="warn">Not applied yet</Badge>}
      </div>
      <ul className="divide-y divide-border">
        {plan.map((a, i) => {
          const isApplied = applied.has(i);
          const r = results[i];
          const Icon = Icons[ACTION_ICON[a.type] ?? "sparkle"];
          const href = r?.ok ? linkFor(a.type, r.id) : null;
          return (
            <li key={i} className={cn("px-3.5 py-2.5", isApplied && "bg-ok-subtle/30")}>
              <div className="flex items-start gap-2.5">
                <input
                  type="checkbox"
                  className="mt-1 size-4 accent-[var(--accent)] disabled:opacity-50"
                  aria-label={`Select: ${a.summary}`}
                  checked={isApplied || selected.has(i)}
                  disabled={isApplied || busy}
                  onChange={(e) => {
                    const next = new Set(selected);
                    if (e.target.checked) next.add(i);
                    else next.delete(i);
                    setSelected(next);
                  }}
                />
                <Icon className="mt-0.5 size-4 shrink-0 text-faint" />
                <div className="min-w-0 flex-1">
                  <div className={cn("text-[13.5px]", isApplied && "text-muted")}>{a.summary}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-[11.5px] text-faint">{a.type}</span>
                    {r && r.ok && (
                      <Badge tone="ok">
                        {href ? (
                          <Link href={href} className="hover:underline">
                            {r.skipped ? "Already applied" : "Applied"} · open
                          </Link>
                        ) : r.skipped ? (
                          "Already applied"
                        ) : (
                          "Applied"
                        )}
                      </Badge>
                    )}
                    {!r && isApplied && <Badge tone="ok">Applied</Badge>}
                    {r && !r.ok && <Badge tone="danger">Failed: {r.error ?? "error"}</Badge>}
                    {r?.note && <span className="text-[12px] text-muted">{r.note}</span>}
                    {r?.warnings?.map((w) => (
                      <Badge key={w} tone="warn">
                        {w}
                      </Badge>
                    ))}
                    <button
                      type="button"
                      className="text-[12px] text-accent hover:underline"
                      aria-expanded={open.has(i)}
                      onClick={() => {
                        const next = new Set(open);
                        if (next.has(i)) next.delete(i);
                        else next.add(i);
                        setOpen(next);
                      }}
                    >
                      {open.has(i) ? "Hide details" : "Details"}
                    </button>
                  </div>
                  {open.has(i) && <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-subtle p-2.5 font-mono text-[11.5px] leading-relaxed">{JSON.stringify(a.data, null, 2)}</pre>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {pending.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-subtle/40 px-3.5 py-2.5">
          <span className="mr-auto text-[12.5px] text-muted">Nothing changes until you apply. Applying the same action twice is safe.</span>
          <Button size="sm" onClick={() => apply([...selected].sort((x, y) => x - y))} disabled={busy || selected.size === 0}>
            Apply selected ({selected.size})
          </Button>
          <Button size="sm" variant="primary" onClick={() => apply()} loading={busy}>
            Apply all
          </Button>
        </div>
      )}
    </Card>
  );
}
