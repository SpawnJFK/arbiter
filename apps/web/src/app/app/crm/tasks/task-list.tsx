"use client";

import Link from "next/link";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { humanize, isPast } from "@/lib/format";
import type { Activity } from "@/lib/types";
import { ACTIVITY_ICON } from "../[id]/account-tabs";

export function TaskList({ initial, accountNames }: { initial: Activity[]; accountNames: Record<string, string> }) {
  const toast = useToast();
  const [items, setItems] = useState(initial);
  const [doneIds, setDoneIds] = useState<Set<string>>(new Set());

  async function done(a: Activity) {
    try {
      await api.updateActivity(a.id, { done: true });
      setDoneIds((s) => new Set(s).add(a.id));
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== a.id)), 600);
    } catch (e) {
      toast.error("Could not update", errorMessage(e));
    }
  }

  if (items.length === 0) {
    return (
      <Card>
        <EmptyState icon={<Icons.check className="size-5" />} title="Nothing open" description="Add tasks from an account's activity timeline." />
      </Card>
    );
  }
  return (
    <Card>
      <ul className="divide-y divide-border">
        {items.map((a) => {
          const Icon = Icons[ACTIVITY_ICON[a.kind] ?? "note"];
          const overdue = isPast(a.due_at);
          const isDone = doneIds.has(a.id);
          return (
            <li key={a.id} className={cn("flex items-start gap-3 px-4 py-3 transition-opacity", isDone && "opacity-40")}>
              <input type="checkbox" className="mt-1 size-4 accent-[var(--accent)]" checked={isDone} onChange={() => done(a)} aria-label={`Mark "${a.body}" done`} />
              <Icon className="mt-0.5 size-4 shrink-0 text-faint" />
              <div className="min-w-0 flex-1">
                <p className={cn("text-[14px]", isDone && "line-through")}>{a.body}</p>
                <p className="mt-0.5 text-[12.5px] text-muted">
                  {humanize(a.kind)} ·{" "}
                  <Link href={`/app/crm/${a.account_id}`} className="hover:text-accent hover:underline">
                    {accountNames[a.account_id] ?? "Account"}
                  </Link>
                </p>
              </div>
              {a.due_at ? (
                <Badge tone={overdue ? "danger" : "warn"}>
                  {overdue ? "Overdue · " : "Due "}
                  <Time iso={a.due_at} mode="relative" />
                </Badge>
              ) : (
                <span className="text-[12px] text-faint">No due date</span>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
