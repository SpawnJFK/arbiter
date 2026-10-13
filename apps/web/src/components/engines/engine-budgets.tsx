"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { EmptyState, Progress } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { EngineBudget } from "@/lib/types";

/** Monthly cost caps per provider. A capped provider is skipped; when nothing is left the
 *  job waits in "needs attention" and resumes by itself once the cap is raised. */
export function EngineBudgets({ initial, providers, currency }: { initial: EngineBudget[]; providers: string[]; currency: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const [budgets, setBudgets] = useState(initial);
  const [editing, setEditing] = useState<{ provider: string; cap: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setBusy(true);
    try {
      const b = await api.putEngineBudget(editing.provider, { monthly_cap: editing.cap });
      setBudgets((xs) => [...xs.filter((x) => x.provider !== b.provider), b].sort((a, z) => a.provider.localeCompare(z.provider)));
      setEditing(null);
    } catch (err) {
      toast.error(t("engines.budgets.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(b: EngineBudget) {
    try {
      await api.deleteEngineBudget(b.provider);
      setBudgets((xs) => xs.filter((x) => x.provider !== b.provider));
    } catch (err) {
      toast.error(t("engines.budgets.couldNotSave"), errorMessage(err));
    }
  }

  return (
    <Card>
      <CardHeader
        title={t("engines.budgets.title")}
        description={t("engines.budgets.description")}
        actions={
          <Button onClick={() => setEditing({ provider: providers[0] ?? "anthropic", cap: "" })}>
            <Icons.plus className="size-4" /> {t("engines.budgets.newCap")}
          </Button>
        }
      />
      {budgets.length === 0 ? (
        <EmptyState title={t("engines.budgets.empty")} description={t("engines.budgets.emptyDescription")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("engines.catalog.provider")}</Th>
              <Th className="text-right">{t("engines.budgets.cap")}</Th>
              <Th className="text-right">{t("engines.budgets.spent")}</Th>
              <Th className="hidden w-40 md:table-cell">
                <span className="sr-only">{t("engines.budgets.usage")}</span>
              </Th>
              <Th className="text-right">
                <span className="sr-only">{t("engines.catalog.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {budgets.map((b) => {
              const cap = Number(b.monthly_cap);
              const pct = cap > 0 ? Math.min(100, (Number(b.spent) / cap) * 100) : 100;
              return (
                <Tr key={b.provider}>
                  <Td>
                    <span className="font-mono text-[12.5px]">{b.provider}</span>
                    {b.exceeded && (
                      <Badge className="ml-2" tone="danger">
                        {t("engines.budgets.exceeded")}
                      </Badge>
                    )}
                  </Td>
                  <Td className="text-right font-mono tabular-nums">
                    {b.monthly_cap} {b.currency}
                  </Td>
                  <Td className="text-right font-mono tabular-nums">{b.spent}</Td>
                  <Td className="hidden md:table-cell">
                    <Progress value={pct} tone={b.exceeded ? "danger" : "accent"} />
                  </Td>
                  <Td className="whitespace-nowrap text-right">
                    <Button size="sm" variant="ghost" onClick={() => setEditing({ provider: b.provider, cap: b.monthly_cap })}>
                      {t("engines.budgets.edit")}
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={t("engines.budgets.remove")} onClick={() => remove(b)}>
                      <Icons.trash className="size-3.5" />
                    </Button>
                  </Td>
                </Tr>
              );
            })}
          </TBody>
        </Table>
      )}
      <Dialog open={editing !== null} onClose={() => setEditing(null)} size="sm" title={t("engines.budgets.dialogTitle")}>
        {editing && (
          <form onSubmit={save} className="space-y-4">
            <Field label={t("engines.catalog.provider")}>
              {(id) => (
                <Select id={id} value={editing.provider} onChange={(e) => setEditing({ ...editing, provider: e.target.value })}>
                  {providers.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("engines.budgets.capLabel", { currency })} hint={t("engines.budgets.capHint")}>
              {(id, d) => (
                <Input
                  id={id}
                  aria-describedby={d}
                  inputMode="decimal"
                  required
                  pattern="[0-9]+([.][0-9]{1,4})?"
                  value={editing.cap}
                  onChange={(e) => setEditing({ ...editing, cap: e.target.value })}
                />
              )}
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(null)}>
                {t("engines.cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={busy}>
                {t("engines.budgets.save")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </Card>
  );
}
