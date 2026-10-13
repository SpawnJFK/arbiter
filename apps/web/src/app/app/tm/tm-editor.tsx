"use client";

import { useI18n } from "@/lib/i18n/client";
import { useCallback, useEffect, useState } from "react";
import { Icons } from "@/components/icons";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import type { TmEntryQuery, TmEntryRow } from "@/lib/types-workbench";

const PAGE = 50;

export function TmEditor({ canEdit }: { canEdit: boolean }) {
  const { t } = useI18n();
  const toast = useToast();
  const [query, setQuery] = useState<TmEntryQuery>({});
  const [draftQ, setDraftQ] = useState("");
  const [rows, setRows] = useState<TmEntryRow[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<{ id: string; target: string } | null>(null);

  const load = useCallback(
    async (q: TmEntryQuery, offset = 0) => {
      try {
        const res = await api.tmEntries({ ...q, offset, limit: PAGE });
        setRows((rs) => (offset === 0 ? res.items : [...(rs ?? []), ...res.items]));
        setNext(res.next_offset);
      } catch (e) {
        toast.error(t("app.tm.editor.loadFailed"), errorMessage(e));
      }
    },
    [toast, t],
  );

  useEffect(() => {
    let live = true;
    api
      .tmEntries({ limit: PAGE })
      .then((res) => {
        if (!live) return;
        setRows(res.items);
        setNext(res.next_offset);
      })
      .catch(() => live && setRows([]));
    return () => {
      live = false;
    };
  }, []);

  function apply(q: TmEntryQuery) {
    setQuery(q);
    setSelected(new Set());
    void load(q);
  }

  async function bulk(action: "delete" | "mark_stale" | "mark_approved") {
    if (selected.size === 0) return;
    try {
      const res = await api.bulkTmEntries([...selected], action);
      toast.success(t("app.tm.editor.bulkDone", { n: res.changed }));
      setSelected(new Set());
      void load(query);
    } catch (e) {
      toast.error(t("app.tm.editor.saveFailed"), errorMessage(e));
    }
  }

  async function saveTarget() {
    if (!editing) return;
    try {
      const row = await api.updateTmEntry(editing.id, { target_tagged: editing.target });
      setRows((rs) => (rs ?? []).map((r) => (r.id === row.id ? row : r)));
      setEditing(null);
    } catch (e) {
      toast.error(t("app.tm.editor.saveFailed"), errorMessage(e));
    }
  }

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <Card>
      <form
        className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          apply({ ...query, q: draftQ.trim() || undefined });
        }}
      >
        <div className="relative min-w-48 flex-1">
          <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
          <Input aria-label={t("app.tm.editor.search")} placeholder={t("app.tm.editor.search")} className="pl-8" value={draftQ} onChange={(e) => setDraftQ(e.target.value)} />
        </div>
        <Select aria-label={t("app.tm.tmScreen.sourceLanguage")} className="w-24" value={query.source_lang ?? ""} onChange={(e) => apply({ ...query, source_lang: e.target.value || undefined })}>
          <option value="">{t("app.tm.editor.anyLang")}</option>
          {LANGS.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </Select>
        <Select aria-label={t("app.tm.tmScreen.targetLanguage")} className="w-24" value={query.target_lang ?? ""} onChange={(e) => apply({ ...query, target_lang: e.target.value || undefined })}>
          <option value="">{t("app.tm.editor.anyLang")}</option>
          {LANGS.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </Select>
        <Select aria-label={t("app.tm.editor.origin")} className="w-32" value={query.origin ?? ""} onChange={(e) => apply({ ...query, origin: e.target.value || undefined })}>
          <option value="">{t("app.tm.editor.anyOrigin")}</option>
          <option value="review">{t.enumLabel("review")}</option>
          <option value="import">{t.enumLabel("import")}</option>
          <option value="client">{t.enumLabel("client")}</option>
        </Select>
        <Select aria-label={t("app.tm.editor.status")} className="w-32" value={query.status ?? ""} onChange={(e) => apply({ ...query, status: e.target.value || undefined })}>
          <option value="">{t("app.tm.editor.anyStatus")}</option>
          <option value="approved">{t.enumLabel("approved")}</option>
          <option value="imported">{t.enumLabel("imported")}</option>
          <option value="stale">{t.enumLabel("stale")}</option>
        </Select>
        <Input type="date" aria-label={t("app.tm.editor.from")} className="w-36" value={query.created_from ?? ""} onChange={(e) => apply({ ...query, created_from: e.target.value || undefined })} />
        <Input type="date" aria-label={t("app.tm.editor.to")} className="w-36" value={query.created_to ?? ""} onChange={(e) => apply({ ...query, created_to: e.target.value || undefined })} />
        <Button type="submit" size="sm">{t("app.tm.editor.apply")}</Button>
      </form>
      {canEdit && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-subtle/50 px-4 py-2 text-[13px]">
          <span>{t("app.tm.editor.selected", { n: selected.size })}</span>
          <Button size="sm" onClick={() => void bulk("mark_stale")}>{t("app.tm.editor.markStale")}</Button>
          <Button size="sm" onClick={() => void bulk("mark_approved")}>{t("app.tm.editor.markApproved")}</Button>
          <Button size="sm" variant="outline-danger" onClick={() => void bulk("delete")}>
            <Icons.trash className="size-3.5" /> {t("app.tm.editor.delete")}
          </Button>
        </div>
      )}
      {rows === null ? null : rows.length === 0 ? (
        <EmptyState title={t("app.tm.editor.empty")} />
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li key={r.id} className="grid gap-3 px-4 py-3 text-[13.5px] sm:grid-cols-[auto_1fr_1fr_auto]">
              {canEdit ? (
                <input type="checkbox" aria-label={t("app.tm.editor.select")} checked={selected.has(r.id)} onChange={() => toggle(r.id)} className="mt-1 size-4 accent-[var(--accent)]" />
              ) : (
                <span />
              )}
              <TaggedText value={r.source_tagged} />
              {editing?.id === r.id ? (
                <form
                  className="flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void saveTarget();
                  }}
                >
                  <Input aria-label={t("app.tm.editor.target")} value={editing.target} onChange={(e) => setEditing({ id: r.id, target: e.target.value })} autoFocus />
                  <Button type="submit" size="sm" variant="primary">{t("app.tm.editor.save")}</Button>
                </form>
              ) : (
                <TaggedText value={r.target_tagged} />
              )}
              <div className="flex flex-col items-end gap-1 text-[12px] text-faint">
                <Badge tone={r.status === "stale" ? "warn" : "neutral"}>{t.enumLabel(r.status)}</Badge>
                <span>
                  {r.source_lang} → {r.target_lang} · {t.enumLabel(r.origin)}
                </span>
                <Time iso={r.updated_at} mode="relative" />
                {canEdit && editing?.id !== r.id && (
                  <Button size="sm" variant="ghost" onClick={() => setEditing({ id: r.id, target: r.target_tagged })}>
                    <Icons.edit className="size-3.5" /> {t("app.tm.editor.edit")}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {next !== null && (
        <div className="border-t border-border px-4 py-3">
          <Button size="sm" onClick={() => void load(query, next)}>
            {t("app.tm.editor.more")}
          </Button>
        </div>
      )}
    </Card>
  );
}
