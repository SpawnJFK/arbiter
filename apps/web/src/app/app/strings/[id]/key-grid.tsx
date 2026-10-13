"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout, EmptyState, Progress, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import {
  loadAllKeys,
  stateOf,
  stringsApi,
  valueText,
  type StringBatch,
  type StringKey,
  type StringKind,
  type StringState,
} from "@/lib/strings";
import { KeyEditor } from "./key-editor";
import type { WorkspaceCtx } from "./workspace";

const ROW = 60;
const VIEW = 600;
const OVERSCAN = 8;
const FILTERS = ["all", "untranslated", "machine", "reviewed", "approved", "blocked", "needs_review"] as const;
type Filter = (typeof FILTERS)[number];

export const STATE_TONE: Record<StringState, Tone> = {
  untranslated: "neutral",
  machine: "info",
  reviewed: "violet",
  approved: "ok",
};

export function StateBadge({ state, blocked }: { state: StringState; blocked?: boolean }) {
  const { t } = useI18n();
  if (blocked) return <Badge tone="danger">{t("app.strings.state.blocked")}</Badge>;
  return <Badge tone={STATE_TONE[state]}>{t(`app.strings.state.${state}`)}</Badge>;
}

export function KeyGrid({ ctx }: { ctx: WorkspaceCtx }) {
  const { t, f } = useI18n();
  const toast = useToast();
  const { project, branch } = ctx;
  const readOnly = Boolean(branch.merged_at);
  const [lang, setLang] = useState(project.target_langs[0] ?? project.base_lang);
  const [all, setAll] = useState<StringKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [batch, setBatch] = useState<StringBatch | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setAll(await loadAllKeys(project.id, { branch: branch.id, langs: project.target_langs.join(",") }));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [project.id, project.target_langs, branch.id]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setAll(null);
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  // Resume progress of a batch that is still running (e.g. after a reload).
  useEffect(() => {
    stringsApi
      .batches(project.id)
      .then((r) => {
        const running = r.items.find((b) => b.status === "queued" || b.status === "running");
        if (running) setBatch(running);
      })
      .catch(() => undefined);
  }, [project.id]);

  useEffect(() => {
    if (!batch || batch.status === "done" || batch.status === "failed") return;
    const timer = setTimeout(async () => {
      try {
        const next = await stringsApi.batch(project.id, batch.id);
        setBatch(next);
        if (next.status === "done") {
          toast.success(t("app.strings.grid.batchDone"), t("app.strings.grid.batchCounts", countsVars(next)));
          void load();
          void ctx.reloadProject();
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearTimeout(timer);
  }, [batch, project.id, load, toast, t, ctx]);

  const tags = useMemo(() => Array.from(new Set((all ?? []).flatMap((k) => k.tags))).sort(), [all]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (all ?? []).filter((k) => {
      const tr = k.translations[lang];
      if (tag && !k.tags.includes(tag)) return false;
      if (filter === "blocked" && !tr?.blocked) return false;
      if (filter === "needs_review" && !tr?.needs_review) return false;
      if (FILTERS.indexOf(filter) > 0 && FILTERS.indexOf(filter) < 5 && stateOf(tr) !== filter) return false;
      if (filter === "untranslated" && !k.translatable) return false;
      if (!needle) return true;
      const hay = [k.name, k.namespace, k.description, valueText(k.translations[project.base_lang]), valueText(tr), ...k.tags];
      return hay.some((h) => h?.toLowerCase().includes(needle));
    });
  }, [all, q, filter, tag, lang, project.base_lang]);

  const selectedKey = rows.find((k) => k.id === selected) ?? (all ?? []).find((k) => k.id === selected) ?? null;
  const start = Math.max(0, Math.floor(scrollTop / ROW) - OVERSCAN);
  const end = Math.min(rows.length, Math.ceil((scrollTop + VIEW) / ROW) + OVERSCAN);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const idx = rows.findIndex((k) => k.id === selected);
    const next = rows[Math.min(rows.length - 1, Math.max(0, idx + (e.key === "ArrowDown" ? 1 : -1)))];
    if (!next) return;
    setSelected(next.id);
    const el = listRef.current;
    const pos = rows.indexOf(next) * ROW;
    if (el && (pos < el.scrollTop || pos + ROW > el.scrollTop + VIEW)) el.scrollTop = pos - VIEW / 2;
  }

  function replaceKey(k: StringKey) {
    setAll((cur) => (cur ? cur.map((x) => (x.id === k.id ? k : x)) : cur));
  }

  async function translateMissing(mode: "translate" | "tm_only") {
    try {
      const b = await stringsApi.translate(project.id, { branch: branch.id, langs: [lang], mode });
      setBatch(b);
      if (b.total === 0) toast.toast({ title: t("app.strings.grid.nothingMissing") });
    } catch (e) {
      toast.error(t("app.strings.grid.translateFailed"), errorMessage(e));
    }
  }

  async function bulk(action: "approve" | "clear") {
    try {
      const r = await stringsApi.bulk(project.id, { action, branch: branch.id, langs: [lang], key_ids: rows.map((k) => k.id) });
      toast.success(t("app.strings.grid.bulkDone", { count: r.changed ?? 0 }));
      void load();
    } catch (e) {
      toast.error(t("app.strings.grid.bulkFailed"), errorMessage(e));
    }
  }

  if (error) {
    return (
      <Callout tone="danger" title={t("app.strings.loadFailed")}>
        {error}
      </Callout>
    );
  }
  const running = batch && (batch.status === "queued" || batch.status === "running");
  const stats = project.stats?.languages[lang];
  return (
    <div className="space-y-3">
      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[12.5px] text-muted">
            {t("app.strings.grid.language")}
            <Select value={lang} onChange={(e) => setLang(e.target.value)} className="mt-1 w-44">
              {project.target_langs.map((l) => (
                <option key={l} value={l}>
                  {f.langName(l)} ({l})
                </option>
              ))}
            </Select>
          </label>
          <label className="min-w-48 flex-1 text-[12.5px] text-muted">
            {t("app.strings.grid.search")}
            <div className="relative mt-1">
              <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-faint" aria-hidden="true" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("app.strings.grid.searchPlaceholder")} className="pl-8" />
            </div>
          </label>
          <label className="text-[12.5px] text-muted">
            {t("app.strings.grid.state")}
            <Select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} className="mt-1 w-40">
              {FILTERS.map((x) => (
                <option key={x} value={x}>
                  {x === "all" ? t("app.strings.grid.allStates") : t(`app.strings.state.${x}`)}
                </option>
              ))}
            </Select>
          </label>
          <label className="text-[12.5px] text-muted">
            {t("app.strings.grid.tag")}
            <Select value={tag} onChange={(e) => setTag(e.target.value)} className="mt-1 w-36">
              <option value="">{t("app.strings.grid.allTags")}</option>
              {tags.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </Select>
          </label>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button onClick={() => setAdding(true)} disabled={readOnly}>
              <Icons.plus className="size-4" /> {t("app.strings.grid.addKey")}
            </Button>
            <Button onClick={() => translateMissing("tm_only")} disabled={readOnly || Boolean(running)}>
              <Icons.db className="size-4" /> {t("app.strings.grid.pretranslateTm")}
            </Button>
            <Button variant="primary" onClick={() => translateMissing("translate")} disabled={readOnly || Boolean(running)}>
              <Icons.sparkle className="size-4" /> {t("app.strings.grid.translateMissing")}
            </Button>
          </div>
        </div>
        {running && batch && (
          <div className="mt-3 flex items-center gap-3" aria-live="polite">
            <Progress value={batch.progress} className="flex-1" />
            <span className="tabular text-[12.5px] text-muted">
              {t("app.strings.grid.batchProgress", { done: batch.done, total: batch.total })}
            </span>
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-muted">
          <span>{t("app.strings.grid.showing", { shown: rows.length, total: all?.length ?? 0 })}</span>
          {stats && (
            <span>
              {t("app.strings.grid.langStats", {
                progress: stats.progress,
                approved: stats.approved,
                reviewed: stats.reviewed,
                machine: stats.machine,
                blocked: stats.blocked,
              })}
            </span>
          )}
          <span className="ml-auto flex gap-2">
            <Button size="sm" onClick={() => bulk("approve")} disabled={readOnly || rows.length === 0}>
              <Icons.check className="size-3.5" /> {t("app.strings.grid.approveVisible")}
            </Button>
            <Button size="sm" variant="outline-danger" onClick={() => setConfirmClear(true)} disabled={readOnly || rows.length === 0}>
              {t("app.strings.grid.clearVisible")}
            </Button>
          </span>
        </div>
      </Card>

      <div className="flex flex-col gap-3 lg:flex-row">
        <Card className="min-w-0 flex-1 overflow-hidden">
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_6.5rem] gap-3 border-b sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1.3fr)_minmax(0,1.3fr)_7rem] border-border bg-subtle px-3 py-2 text-[12px] font-medium text-muted">
            <span>{t("app.strings.grid.key")}</span>
            <span className="hidden sm:block">{t("app.strings.grid.source", { lang: project.base_lang })}</span>
            <span>{t("app.strings.grid.target", { lang })}</span>
            <span>{t("app.strings.grid.state")}</span>
          </div>
          {all === null ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              title={all.length === 0 ? t("app.strings.grid.noKeys") : t("app.strings.grid.noMatch")}
              description={all.length === 0 ? t("app.strings.grid.noKeysHint") : undefined}
            />
          ) : (
            <div
              ref={listRef}
              role="grid"
              aria-rowcount={rows.length}
              aria-label={t("app.strings.grid.keys")}
              tabIndex={0}
              onKeyDown={onKeyDown}
              onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
              className="overflow-y-auto focus-visible:outline-2 focus-visible:outline-ring"
              style={{ height: Math.min(VIEW, rows.length * ROW) }}
            >
              <div style={{ height: rows.length * ROW, position: "relative" }}>
                {rows.slice(start, end).map((k, i) => {
                  const tr = k.translations[lang];
                  const base = k.translations[project.base_lang];
                  return (
                    <div
                      key={k.id}
                      role="row"
                      aria-rowindex={start + i + 1}
                      aria-selected={k.id === selected}
                      onClick={() => setSelected(k.id)}
                      style={{ position: "absolute", top: (start + i) * ROW, height: ROW, left: 0, right: 0 }}
                      className={cn(
                        "grid cursor-pointer grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_6.5rem] items-center sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1.3fr)_minmax(0,1.3fr)_7rem] gap-3 border-b border-border px-3 text-[13px] hover:bg-hover",
                        k.id === selected && "bg-accent-subtle",
                      )}
                    >
                      <div role="gridcell" className="min-w-0">
                        <div className="truncate font-mono text-[12.5px] text-fg" title={k.name}>
                          {k.namespace && <span className="text-muted">{k.namespace}:</span>}
                          {k.name}
                        </div>
                        <div className="mt-0.5 flex gap-1 overflow-hidden">
                          {k.kind !== "string" && <Badge tone="info">{t(`app.strings.kind.${k.kind}`)}</Badge>}
                          {k.branch_local && <Badge tone="violet">{t("app.strings.grid.branchOnly")}</Badge>}
                          {k.tags.slice(0, 2).map((x) => (
                            <Badge key={x}>{x}</Badge>
                          ))}
                        </div>
                      </div>
                      <div role="gridcell" className="hidden min-w-0 text-muted sm:line-clamp-2" title={valueText(base)}>
                        {valueText(base)}
                      </div>
                      <div role="gridcell" className={cn("line-clamp-2 min-w-0", !tr && "italic text-faint")}>
                        {tr ? valueText(tr) : k.translatable ? t("app.strings.grid.empty") : t("app.strings.grid.notTranslatable")}
                      </div>
                      <div role="gridcell" className="flex flex-col items-start gap-0.5">
                        {k.translatable ? <StateBadge state={stateOf(tr)} blocked={tr?.blocked} /> : <span className="text-faint">-</span>}
                        {tr?.qe_score != null && <span className="tabular text-[11.5px] text-muted">{t("app.strings.grid.qe", { score: Math.round(tr.qe_score) })}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </Card>
        {selectedKey && (
          <KeyEditor
            key={`${selectedKey.id}:${lang}:${branch.id}`}
            ctx={ctx}
            item={selectedKey}
            lang={lang}
            readOnly={readOnly}
            onChange={replaceKey}
            onClose={() => setSelected(null)}
          />
        )}
      </div>

      <AddKeyDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={(k) => {
          setAll((cur) => [...(cur ?? []), k]);
          setSelected(k.id);
        }}
        ctx={ctx}
      />
      <Dialog
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        title={t("app.strings.grid.clearTitle")}
        description={t("app.strings.grid.clearBody", { count: rows.length, lang })}
        size="sm"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmClear(false)}>
              {t("app.strings.cancel")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirmClear(false);
                void bulk("clear");
              }}
            >
              {t("app.strings.grid.clearVisible")}
            </Button>
          </div>
        }
      />
    </div>
  );
}

function countsVars(b: StringBatch) {
  const c = b.counts;
  return {
    machine: (c.machine ?? 0) + (c.tm ?? 0),
    reviewed: c.reviewed ?? 0,
    blocked: c.blocked ?? 0,
    review: c.review_tasks ?? 0,
  };
}

function AddKeyDialog({
  open,
  onClose,
  onCreated,
  ctx,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (k: StringKey) => void;
  ctx: WorkspaceCtx;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [name, setName] = useState("");
  const [namespace, setNamespace] = useState("");
  const [kind, setKind] = useState<StringKind>("string");
  const [value, setValue] = useState("");
  const [one, setOne] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const k = await stringsApi.createKey(
        ctx.project.id,
        {
          name: name.trim(),
          namespace: namespace.trim(),
          kind,
          description,
          ...(kind === "plural" ? { forms: { one, other: value } } : kind === "array" ? { forms: { "0": value } } : { value }),
        },
        ctx.branch.id,
      );
      toast.success(t("app.strings.grid.keyCreated"));
      onCreated(k);
      onClose();
      setName("");
      setValue("");
      setOne("");
      setDescription("");
    } catch (err) {
      toast.error(t("app.strings.grid.keyFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("app.strings.grid.addKey")} size="md">
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
          <Field label={t("app.strings.grid.keyName")}>{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} className="font-mono" autoFocus />}</Field>
          <Field label={t("app.strings.grid.namespace")}>{(id) => <Input id={id} value={namespace} onChange={(e) => setNamespace(e.target.value)} />}</Field>
        </div>
        <Field label={t("app.strings.grid.kind")}>
          {(id) => (
            <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as StringKind)}>
              {(["string", "plural", "array"] as const).map((x) => (
                <option key={x} value={x}>
                  {t(`app.strings.kind.${x}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {kind === "plural" && (
          <Field label={t("app.strings.grid.formOne", { lang: ctx.project.base_lang })}>{(id) => <Input id={id} value={one} onChange={(e) => setOne(e.target.value)} />}</Field>
        )}
        <Field label={kind === "plural" ? t("app.strings.grid.formOther", { lang: ctx.project.base_lang }) : t("app.strings.grid.sourceText", { lang: ctx.project.base_lang })}>
          {(id) => <Textarea id={id} required value={value} onChange={(e) => setValue(e.target.value)} rows={2} />}
        </Field>
        <Field label={t("app.strings.editor.description")} hint={t("app.strings.editor.descriptionHint")}>
          {(id, d) => <Textarea id={id} aria-describedby={d} value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />}
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            {t("app.strings.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!name.trim() || !value.trim()}>
            {t("app.strings.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
