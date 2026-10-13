"use client";

import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { stringsApi, type MergeConflict, type StringBranch } from "@/lib/strings";
import type { WorkspaceCtx } from "./workspace";

function show(v: MergeConflict["main_value"]): string {
  if (v === null) return "";
  return typeof v === "string" ? v : Object.entries(v).map(([k, x]) => `${k}: ${x}`).join("\n");
}

/** Copy-on-write branches: create, open, merge into main (with conflict resolution), delete. */
export function Branches({ ctx, onOpen }: { ctx: WorkspaceCtx; onOpen: (id: string) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const { project, branches } = ctx;
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [merging, setMerging] = useState<{ branch: StringBranch; conflicts: MergeConflict[] } | null>(null);
  const [choice, setChoice] = useState<Record<string, "branch" | "main">>({});

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await stringsApi.createBranch(project.id, name.trim());
      setName("");
      await ctx.reloadBranches();
      toast.success(t("app.strings.branches.created"));
    } catch (err) {
      toast.error(t("app.strings.branches.createFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function preview(b: StringBranch) {
    try {
      const r = await stringsApi.mergePreview(project.id, b.id);
      setChoice({});
      setMerging({ branch: b, conflicts: r.conflicts });
    } catch (err) {
      toast.error(t("app.strings.branches.mergeFailed"), errorMessage(err));
    }
  }

  async function merge() {
    if (!merging) return;
    setBusy(true);
    try {
      const r = await stringsApi.merge(project.id, merging.branch.id, choice);
      toast.success(t("app.strings.branches.merged", { applied: r.applied, keys: r.keys_moved }));
      setMerging(null);
      await ctx.reloadBranches();
      void ctx.reloadProject();
    } catch (err) {
      toast.error(t("app.strings.branches.mergeFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(b: StringBranch) {
    try {
      await stringsApi.deleteBranch(project.id, b.id);
      await ctx.reloadBranches();
      toast.success(t("app.strings.branches.deleted"));
    } catch (err) {
      toast.error(t("app.strings.branches.deleteFailed"), errorMessage(err));
    }
  }

  const unresolved = merging ? merging.conflicts.filter((c) => !choice[`${c.key_id}:${c.lang}`]).length : 0;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("app.strings.branches.title")} description={t("app.strings.branches.hint")} />
        <CardBody>
          <form onSubmit={create} className="mb-4 flex flex-wrap gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("app.strings.branches.namePlaceholder")} aria-label={t("app.strings.branches.name")} className="max-w-xs font-mono" />
            <Button type="submit" loading={busy} disabled={!name.trim()}>
              <Icons.plus className="size-4" /> {t("app.strings.branches.create")}
            </Button>
          </form>
          <Table>
            <THead>
              <tr>
                <Th>{t("app.strings.branches.name")}</Th>
                <Th>{t("app.strings.branches.changes")}</Th>
                <Th>{t("app.strings.branches.createdAt")}</Th>
                <Th className="text-right">{t("app.strings.branches.actions")}</Th>
              </tr>
            </THead>
            <TBody>
              {branches.map((b) => (
                <Tr key={b.id}>
                  <Td>
                    <span className="font-mono text-[13px]">{b.name}</span>{" "}
                    {b.is_main && <Badge tone="accent">{t("app.strings.branches.main")}</Badge>}
                    {b.merged_at && <Badge tone="ok">{t("app.strings.merged")}</Badge>}
                  </Td>
                  <Td className="text-muted">{b.is_main ? "" : t("app.strings.branches.changeCount", { changes: b.changes, keys: b.new_keys })}</Td>
                  <Td className="text-muted">
                    <Time iso={b.merged_at ?? b.created_at} mode="relative" />
                  </Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" onClick={() => onOpen(b.id)}>
                        {t("app.strings.branches.open")}
                      </Button>
                      {!b.is_main && !b.merged_at && (
                        <>
                          <Button size="sm" variant="primary" onClick={() => preview(b)}>
                            {t("app.strings.branches.merge")}
                          </Button>
                          <Button size="sm" variant="outline-danger" onClick={() => remove(b)}>
                            {t("app.strings.branches.delete")}
                          </Button>
                        </>
                      )}
                    </div>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </CardBody>
      </Card>

      <Dialog
        open={merging !== null}
        onClose={() => setMerging(null)}
        title={t("app.strings.branches.mergeTitle", { name: merging?.branch.name ?? "" })}
        size="lg"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setMerging(null)}>
              {t("app.strings.cancel")}
            </Button>
            <Button variant="primary" loading={busy} disabled={unresolved > 0} onClick={merge}>
              {t("app.strings.branches.mergeConfirm")}
            </Button>
          </div>
        }
      >
        {merging && merging.conflicts.length === 0 ? (
          <Callout tone="ok">{t("app.strings.branches.noConflicts", { changes: merging.branch.changes, keys: merging.branch.new_keys })}</Callout>
        ) : (
          <div className="space-y-3">
            <Callout tone="warn">{t("app.strings.branches.conflictsHint", { count: merging?.conflicts.length ?? 0 })}</Callout>
            {merging?.conflicts.map((c) => {
              const id = `${c.key_id}:${c.lang}`;
              return (
                <fieldset key={id} className="rounded-md border border-border p-3">
                  <legend className="px-1 font-mono text-[12.5px]">
                    {c.key} [{c.lang}]
                  </legend>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {(["branch", "main"] as const).map((side) => (
                      <label key={side} className="flex cursor-pointer gap-2 rounded-md border border-border p-2 text-[13px] has-[:checked]:border-accent has-[:checked]:bg-accent-subtle">
                        <input type="radio" name={id} checked={choice[id] === side} onChange={() => setChoice({ ...choice, [id]: side })} />
                        <span>
                          <span className="block text-[12px] font-medium text-muted">
                            {side === "branch" ? t("app.strings.branches.keepBranch") : t("app.strings.branches.keepMain")}
                          </span>
                          <span className="whitespace-pre-wrap">{show(side === "branch" ? c.branch_value : c.main_value) || t("app.strings.grid.empty")}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              );
            })}
          </div>
        )}
      </Dialog>
    </div>
  );
}
