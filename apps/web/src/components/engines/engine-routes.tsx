"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage, type EngineScope } from "@/lib/api";
import type { EnginePurpose, EngineRoute, EngineRouteInput } from "@/lib/types";

const PURPOSES: { value: EnginePurpose; label: string }[] = [
  { value: "mt", label: k("engines.purpose.mt") },
  { value: "judge", label: k("engines.purpose.judge") },
  { value: "senate", label: k("engines.purpose.senate") },
  { value: "editor", label: k("engines.purpose.editor") },
];

const EMPTY: EngineRouteInput = {
  purpose: "mt",
  source_lang: null,
  target_lang: null,
  content_type: null,
  engines: [],
  fallback: true,
  enabled: true,
  note: "",
};

function move<T>(xs: T[], from: number, to: number): T[] {
  const out = [...xs];
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}

/** Routing rules: which engines, in which order, for a pair / content type / purpose. */
export function EngineRoutes({ scope, initial, engineNames }: { scope: EngineScope; initial: EngineRoute[]; engineNames: string[] }) {
  const { t } = useI18n();
  const toast = useToast();
  const [routes, setRoutes] = useState(initial);
  const [editing, setEditing] = useState<{ id: string | null; value: EngineRouteInput } | null>(null);
  const [busy, setBusy] = useState(false);
  const [newEngine, setNewEngine] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const any = t("engines.routes.any");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setBusy(true);
    try {
      const body = editing.value;
      const saved = editing.id
        ? await api.updateEngineRoute(editing.id, body, scope)
        : await api.createEngineRoute(body, scope);
      setRoutes((xs) => (editing.id ? xs.map((x) => (x.id === saved.id ? saved : x)) : [...xs, saved]));
      setEditing(null);
      toast.success(t("engines.routes.saved"));
    } catch (err) {
      toast.error(t("engines.routes.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(r: EngineRoute) {
    try {
      await api.deleteEngineRoute(r.id, scope);
      setRoutes((xs) => xs.filter((x) => x.id !== r.id));
    } catch (err) {
      toast.error(t("engines.routes.couldNotSave"), errorMessage(err));
    }
  }

  const v = editing?.value;
  const setV = (patch: Partial<EngineRouteInput>) => editing && setEditing({ ...editing, value: { ...editing.value, ...patch } });

  return (
    <Card>
      <CardHeader
        title={scope === "platform" ? t("engines.routes.platformTitle") : t("engines.routes.title")}
        description={t("engines.routes.description")}
        actions={
          <Button variant="primary" onClick={() => setEditing({ id: null, value: { ...EMPTY } })}>
            <Icons.plus className="size-4" /> {t("engines.routes.newRule")}
          </Button>
        }
      />
      {routes.length === 0 ? (
        <EmptyState title={t("engines.routes.empty")} description={t("engines.routes.emptyDescription")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("engines.routes.purpose")}</Th>
              <Th>{t("engines.routes.match")}</Th>
              <Th>{t("engines.routes.engines")}</Th>
              <Th className="hidden md:table-cell">{t("engines.routes.fallback")}</Th>
              <Th className="text-right">
                <span className="sr-only">{t("engines.catalog.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {routes.map((r) => (
              <Tr key={r.id} className={r.enabled ? undefined : "opacity-60"}>
                <Td>{t(`engines.purpose.${r.purpose}`)}</Td>
                <Td className="font-mono text-[12.5px]">
                  {(r.source_lang ?? any) + " → " + (r.target_lang ?? any)}
                  <span className="ml-1.5 text-muted">{r.content_type ?? any}</span>
                </Td>
                <Td>
                  <ol className="flex flex-wrap gap-1">
                    {r.engines.map((e, i) => (
                      <li key={e}>
                        <Badge tone={i === 0 ? "accent" : "neutral"}>
                          {i + 1}. {e}
                        </Badge>
                      </li>
                    ))}
                  </ol>
                </Td>
                <Td className="hidden text-[13px] text-muted md:table-cell">{r.fallback ? t("engines.routes.yes") : t("engines.routes.no")}</Td>
                <Td className="whitespace-nowrap text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      const { id, scope: _s, ...value } = r;
                      void _s;
                      setEditing({ id, value });
                    }}
                  >
                    {t("engines.routes.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" aria-label={t("engines.routes.delete")} onClick={() => remove(r)}>
                    <Icons.trash className="size-3.5" />
                  </Button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}

      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id ? t("engines.routes.editTitle") : t("engines.routes.newTitle")}
        description={t("engines.routes.precedence")}
        size="lg"
      >
        {v && (
          <form onSubmit={save} className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label={t("engines.routes.purpose")}>
                {(id) => (
                  <Select id={id} value={v.purpose} onChange={(e) => setV({ purpose: e.target.value as EnginePurpose })}>
                    {PURPOSES.map((p) => (
                      <option key={p.value} value={p.value}>
                        {t(p.label)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={t("engines.routes.sourceLang")}>
                {(id) => <Input id={id} placeholder={any} value={v.source_lang ?? ""} onChange={(e) => setV({ source_lang: e.target.value || null })} />}
              </Field>
              <Field label={t("engines.routes.targetLang")}>
                {(id) => <Input id={id} placeholder={any} value={v.target_lang ?? ""} onChange={(e) => setV({ target_lang: e.target.value || null })} />}
              </Field>
              <Field label={t("engines.routes.contentType")}>
                {(id) => <Input id={id} placeholder={any} value={v.content_type ?? ""} onChange={(e) => setV({ content_type: e.target.value || null })} />}
              </Field>
            </div>

            <fieldset>
              <legend className="mb-1 text-[13px] font-medium">{t("engines.routes.order")}</legend>
              <p className="mb-2 text-[12.5px] text-muted">{t("engines.routes.orderHint")}</p>
              {v.engines.length === 0 ? (
                <p className="rounded-md border border-dashed border-border px-3 py-2 text-[13px] text-muted">{t("engines.routes.noEnginesYet")}</p>
              ) : (
                <ol className="divide-y divide-border rounded-md border border-border">
                  {v.engines.map((e, i) => (
                    <li
                      key={e}
                      draggable
                      onDragStart={() => setDragIndex(i)}
                      onDragOver={(ev) => ev.preventDefault()}
                      onDrop={() => {
                        if (dragIndex !== null && dragIndex !== i) setV({ engines: move(v.engines, dragIndex, i) });
                        setDragIndex(null);
                      }}
                      className="flex cursor-grab items-center gap-2 px-3 py-1.5 text-[13px]"
                    >
                      <span className="w-5 text-right font-mono text-faint">{i + 1}</span>
                      <span className="flex-1 font-mono">{e}</span>
                      <Button size="sm" variant="ghost" aria-label={t("engines.routes.moveUp")} disabled={i === 0} onClick={() => setV({ engines: move(v.engines, i, i - 1) })}>
                        <Icons.up className="size-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("engines.routes.moveDown")}
                        disabled={i === v.engines.length - 1}
                        onClick={() => setV({ engines: move(v.engines, i, i + 1) })}
                      >
                        <Icons.down className="size-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={t("engines.routes.removeEngine")} onClick={() => setV({ engines: v.engines.filter((x) => x !== e) })}>
                        <Icons.trash className="size-3.5" />
                      </Button>
                    </li>
                  ))}
                </ol>
              )}
              <div className="mt-2 flex gap-2">
                <Input
                  aria-label={t("engines.routes.addEngine")}
                  list="engine-names"
                  placeholder={t("engines.routes.enginePlaceholder")}
                  value={newEngine}
                  onChange={(e) => setNewEngine(e.target.value)}
                />
                <datalist id="engine-names">
                  {engineNames.map((n) => (
                    <option key={n} value={n} />
                  ))}
                </datalist>
                <Button
                  disabled={!newEngine.trim() || v.engines.includes(newEngine.trim())}
                  onClick={() => {
                    setV({ engines: [...v.engines, newEngine.trim()] });
                    setNewEngine("");
                  }}
                >
                  {t("engines.routes.add")}
                </Button>
              </div>
            </fieldset>

            <Checkbox label={t("engines.routes.fallbackLabel")} hint={t("engines.routes.fallbackHint")} checked={v.fallback} onChange={(e) => setV({ fallback: e.target.checked })} />
            <Checkbox label={t("engines.routes.enabledLabel")} checked={v.enabled} onChange={(e) => setV({ enabled: e.target.checked })} />
            <Field label={t("engines.routes.note")}>{(id) => <Input id={id} value={v.note} onChange={(e) => setV({ note: e.target.value })} />}</Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(null)}>
                {t("engines.cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={v.engines.length === 0}>
                {t("engines.routes.saveRule")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </Card>
  );
}
