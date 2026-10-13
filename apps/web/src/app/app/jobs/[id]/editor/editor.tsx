"use client";

import { useI18n } from "@/lib/i18n/client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { TagEditor, TagStatus, tagsValid, type TagEditorHandle } from "@/components/tag-editor";
import { TaggedText } from "@/components/tagged-text";
import { Badge, DecisionBadge, SegmentStateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, Kbd } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { tagsOf } from "@/lib/tags";
import { SEGMENT_STATES, type Job } from "@/lib/types";
import {
  TM_BANDS,
  type AssistData,
  type DraftCheck,
  type EditorFilters,
  type EditorSegment,
  type EditorSegmentPage,
  type MtSuggestion,
} from "@/lib/types-workbench";
import { FindReplaceDialog, PreviewDialog, ShortcutsDialog, SplitDialog } from "./editor-dialogs";
import { CommentsPanel, ConcordancePanel, GlossaryPanel, MtPanel, QaPanel, TmPanel } from "./editor-panels";
import { DONE_STATES, ROW_HEIGHT } from "./editor-utils";

type Tab = "tm" | "terms" | "qa" | "mt" | "concordance" | "comments";
const PAGE = 200;
const OPEN_JOB = ["running", "review"];

export function Editor({ job, role, initial }: { job: Job; role: string; initial: EditorSegmentPage }) {
  const { t } = useI18n();
  const toast = useToast();
  const isPm = role === "pm";
  const [rows, setRows] = useState<EditorSegment[]>(initial.items);
  const [total, setTotal] = useState(initial.total);
  const [loadingMore, setLoadingMore] = useState(initial.next_offset !== null);
  const [filters, setFilters] = useState<EditorFilters>({});
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(initial.items[0]?.id ?? null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [check, setCheck] = useState<{ id: string; value: string; data: DraftCheck } | null>(null);
  const [assist, setAssist] = useState<{ id: string; data: AssistData } | null>(null);
  const [mt, setMt] = useState<{ id: string; data: MtSuggestion } | null>(null);
  const [mtBusy, setMtBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("tm");
  const [concordanceQuery, setConcordanceQuery] = useState<{ q: string; n: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [dialog, setDialog] = useState<"find" | "split" | "preview" | "help" | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(600);
  const listRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<TagEditorHandle>(null);
  const generation = useRef(0);

  const index = useMemo(() => rows.findIndex((r) => r.id === activeId), [rows, activeId]);
  const active = index >= 0 ? rows[index] : null;
  const draft = active ? (drafts[active.id] ?? active.target_tagged ?? "") : "";
  const required = useMemo(() => (active ? tagsOf(active.source_tagged) : []), [active]);
  const editable = !!active && OPEN_JOB.includes(job.state) && !["pending", "translated", "in_review"].includes(active.state) && (!active.locked || isPm);
  const dirty = !!active && draft !== (active.target_tagged ?? "");

  // ------------------------------------------------------------------ loading

  const fetchFrom = useCallback(
    async (f: EditorFilters, offset: number, gen: number, replace: boolean) => {
      let next: number | null = offset;
      let first = replace;
      setLoadingMore(true);
      try {
        while (next !== null) {
          const res = await api.editorSegments(job.id, { ...f, offset: next, limit: PAGE });
          if (gen !== generation.current) return;
          const items = res.items;
          setRows((rs) => (first ? items : [...rs, ...items]));
          if (first) setActiveId((cur) => (items.some((s) => s.id === cur) ? cur : (items[0]?.id ?? null)));
          first = false;
          setTotal(res.total);
          next = res.next_offset;
        }
      } catch (e) {
        toast.error(t("app.jobs.editor.loadFailed"), errorMessage(e));
      } finally {
        if (gen === generation.current) setLoadingMore(false);
      }
    },
    [job.id, toast, t],
  );

  useEffect(() => {
    if (initial.next_offset !== null) void fetchFrom({}, initial.next_offset, generation.current, false);
  }, [fetchFrom, initial.next_offset]);

  function applyFilters(f: EditorFilters) {
    setFilters(f);
    generation.current += 1;
    void fetchFrom(f, 0, generation.current, true);
  }

  const reload = useCallback(() => {
    generation.current += 1;
    void fetchFrom(filters, 0, generation.current, true);
  }, [fetchFrom, filters]);

  // live QA of the draft (debounced), TM/glossary assistance per segment
  useEffect(() => {
    if (!active) return;
    const id = active.id;
    const value = draft;
    const timer = setTimeout(() => {
      api
        .checkDraft(job.id, id, value)
        .then((data) => setCheck({ id, value, data }))
        .catch(() => undefined);
    }, 350);
    return () => clearTimeout(timer);
  }, [active, draft, job.id]);

  useEffect(() => {
    if (!activeId) return;
    let live = true;
    api
      .assist(job.id, activeId)
      .then((data) => live && setAssist({ id: activeId, data }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [activeId, job.id]);

  // keep the viewport height for the virtual list
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewport(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ------------------------------------------------------------------ actions

  const select = useCallback(
    (i: number) => {
      const seg = rows[i];
      if (!seg) return;
      setActiveId(seg.id);
      const el = listRef.current;
      if (el) {
        const top = i * ROW_HEIGHT;
        if (top < el.scrollTop) el.scrollTop = top;
        else if (top + ROW_HEIGHT > el.scrollTop + el.clientHeight) el.scrollTop = top + ROW_HEIGHT - el.clientHeight;
      }
      requestAnimationFrame(() => editorRef.current?.focus());
    },
    [rows],
  );

  const setDraft = useCallback(
    (value: string) => {
      if (!active) return;
      setDrafts((d) => ({ ...d, [active.id]: value }));
    },
    [active],
  );

  const patchRow = (seg: Partial<EditorSegment> & { id: string }) =>
    setRows((rs) => rs.map((r) => (r.id === seg.id ? { ...r, ...seg } : r)));

  const confirm = useCallback(async () => {
    if (!active || saving) return;
    if (!editable) {
      select(index + 1);
      return;
    }
    if (!tagsValid(required, draft)) {
      toast.error(t("app.jobs.editor.tagsMissing"), t("app.jobs.editor.tagsMissingHint"));
      return;
    }
    const needs = active.state === "needs_review";
    if (!dirty && !needs) {
      select(index + 1);
      return;
    }
    setSaving(true);
    try {
      const res = needs && !dirty ? await api.approveSegment(job.id, active.id) : await api.editSegment(job.id, active.id, draft);
      patchRow({ ...res, id: active.id });
      setDrafts((d) => {
        const n = { ...d };
        delete n[active.id];
        return n;
      });
      const nextOpen = rows.findIndex((r, i) => i > index && !DONE_STATES.includes(r.state));
      select(nextOpen >= 0 ? nextOpen : index + 1);
    } catch (e) {
      toast.error(t("app.jobs.editor.saveFailed"), errorMessage(e));
    } finally {
      setSaving(false);
    }
  }, [active, saving, editable, required, draft, dirty, job.id, rows, index, select, toast, t]);

  const fetchMt = useCallback(async () => {
    if (!active || !isPm) return;
    setTab("mt");
    setMtBusy(true);
    try {
      setMt({ id: active.id, data: await api.mtSuggest(job.id, active.id) });
    } catch (e) {
      toast.error(t("app.jobs.editor.mtFailed"), errorMessage(e));
    } finally {
      setMtBusy(false);
    }
  }, [active, isPm, job.id, toast, t]);

  const openConcordance = useCallback(() => {
    const sel = typeof window !== "undefined" ? (window.getSelection()?.toString() ?? "").trim() : "";
    setTab("concordance");
    if (sel) setConcordanceQuery((c) => ({ q: sel.slice(0, 200), n: (c?.n ?? 0) + 1 }));
  }, []);

  async function toggleLock() {
    if (!active) return;
    try {
      await api.lockSegments(job.id, [active.id], !active.locked);
      patchRow({ id: active.id, locked: !active.locked });
    } catch (e) {
      toast.error(t("app.jobs.editor.lockFailed"), errorMessage(e));
    }
  }

  async function mergeNext() {
    if (!active) return;
    try {
      await api.mergeNext(job.id, active.id);
      toast.success(t("app.jobs.editor.merged"));
      reload();
    } catch (e) {
      toast.error(t("app.jobs.editor.mergeFailed"), errorMessage(e));
    }
  }

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (dialog) return;
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      if (e.key === "Enter") {
        e.preventDefault();
        void confirm();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        select(Math.min(rows.length - 1, index + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        select(Math.max(0, index - 1));
      } else if (e.shiftKey && (e.key === "F" || e.key === "f")) {
        e.preventDefault();
        setDialog("find");
      } else if (!e.shiftKey && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        openConcordance();
      } else if (!e.shiftKey && (e.key === "m" || e.key === "M")) {
        e.preventDefault();
        void fetchMt();
      } else if (e.key === "Insert") {
        e.preventDefault();
        if (active && editable) setDraft(active.source_tagged);
      } else if (["1", "2", "3"].includes(e.key) && !e.shiftKey) {
        const m = assist && active && assist.id === active.id ? assist.data.tm_matches[Number(e.key) - 1] : undefined;
        if (m && editable) {
          e.preventDefault();
          setDraft(m.target_tagged);
        }
      }
    },
    [dialog, confirm, select, rows.length, index, openConcordance, fetchMt, active, editable, setDraft, assist],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  // ------------------------------------------------------------------ render

  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 6);
  const last = Math.min(rows.length, Math.ceil((scrollTop + viewport) / ROW_HEIGHT) + 6);
  const visible = rows.slice(first, last);
  const liveCheck = check && active && check.id === active.id && check.value === draft ? check.data : null;
  const assistData = assist && active && assist.id === active.id ? assist.data : null;
  const mtData = mt && active && mt.id === active.id ? mt.data : null;
  const done = rows.filter((r) => DONE_STATES.includes(r.state)).length;
  const toggle = (key: keyof EditorFilters) => applyFilters({ ...filters, [key]: filters[key] ? undefined : "true" });

  return (
    <div className="space-y-3">
      <Card className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <form
          className="relative min-w-48 flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            applyFilters({ ...filters, q: search.trim() || undefined });
          }}
        >
          <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
          <Input
            aria-label={t("app.jobs.editor.searchSegments")}
            placeholder={t("app.jobs.editor.searchSegments")}
            className="pl-8"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <Select
          aria-label={t("app.jobs.editor.filterState")}
          className="w-40"
          value={filters.state ?? ""}
          onChange={(e) => applyFilters({ ...filters, state: e.target.value || undefined })}
        >
          <option value="">{t("app.jobs.editor.allStates")}</option>
          {SEGMENT_STATES.map((s) => (
            <option key={s} value={s}>
              {t.enumLabel(s)}
            </option>
          ))}
        </Select>
        <Select
          aria-label={t("app.jobs.editor.filterTmBand")}
          className="w-36"
          value={filters.tm_band ?? ""}
          onChange={(e) => applyFilters({ ...filters, tm_band: e.target.value || undefined })}
        >
          <option value="">{t("app.jobs.editor.anyTmMatch")}</option>
          {TM_BANDS.map((b) => (
            <option key={b} value={b}>
              {b === "none" ? t("app.jobs.editor.noTmMatch") : b === "lt75" ? t("app.jobs.editor.below75") : `${b}%`}
            </option>
          ))}
        </Select>
        {(
          [
            ["qa", t("app.jobs.editor.withQaIssues")],
            ["has_comment", t("app.jobs.editor.withComments")],
            ["open_query", t("app.jobs.editor.openQueries")],
            ["locked", t("app.jobs.editor.locked")],
          ] as [keyof EditorFilters, string][]
        ).map(([key, label]) => (
          <Button key={key} size="sm" variant={filters[key] ? "primary" : "secondary"} aria-pressed={!!filters[key]} onClick={() => toggle(key)}>
            {label}
          </Button>
        ))}
        <div className="ml-auto flex items-center gap-1.5">
          <Button size="sm" onClick={() => setDialog("find")} title={t("app.jobs.editor.findReplaceHint")}>
            <Icons.search className="size-3.5" /> {t("app.jobs.editor.findReplace")}
          </Button>
          <Button size="sm" onClick={() => setDialog("preview")}>
            {t("app.jobs.editor.preview")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDialog("help")} aria-label={t("app.jobs.editor.shortcuts")}>
            <Icons.keyboard className="size-4" />
          </Button>
        </div>
      </Card>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-3">
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-3 py-2 text-[12.5px] text-muted">
              <span className="tabular">
                {t("app.jobs.editor.counter", { shown: rows.length, total, done })}
                {loadingMore && <span className="ml-2 text-faint">{t("app.jobs.editor.loadingMore")}</span>}
              </span>
              <span className="hidden sm:inline">
                <Kbd>Ctrl</Kbd> <Kbd>↑</Kbd> <Kbd>↓</Kbd> {t("app.jobs.editor.toMove")}
              </span>
            </div>
            {rows.length === 0 ? (
              <EmptyState title={t("app.jobs.editor.noSegments")} description={t("app.jobs.editor.noSegmentsHint")} />
            ) : (
              <div
                ref={listRef}
                role="listbox"
                aria-label={t("app.jobs.editor.segmentList")}
                className="relative h-[44vh] min-h-64 overflow-y-auto"
                onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
              >
                <div style={{ height: rows.length * ROW_HEIGHT }} className="relative">
                  {visible.map((s, k) => {
                    const i = first + k;
                    const isActive = s.id === activeId;
                    return (
                      <button
                        key={s.id}
                        type="button"
                        role="option"
                        aria-selected={isActive}
                        onClick={() => select(i)}
                        style={{ top: i * ROW_HEIGHT, height: ROW_HEIGHT }}
                        className={cn(
                          "absolute inset-x-0 grid grid-cols-[44px_minmax(0,1fr)_minmax(0,1fr)_auto] items-start gap-3 border-b border-border px-3 py-2 text-left text-[13px]",
                          isActive ? "bg-accent-subtle" : "hover:bg-hover",
                          drafts[s.id] !== undefined && "border-l-2 border-l-warn",
                        )}
                      >
                        <span className="tabular text-faint">{s.seq + 1}</span>
                        <span className="line-clamp-3 text-muted">
                          <TaggedText value={s.source_tagged} />
                        </span>
                        <span className="line-clamp-3">
                          <TaggedText value={drafts[s.id] ?? s.target_tagged} />
                        </span>
                        <span className="flex flex-col items-end gap-1">
                          <SegmentStateBadge state={s.state} origin={s.origin} />
                          <span className="flex items-center gap-1 text-[11px] text-faint">
                            {s.tm_match !== null && <span className="tabular">{Math.round(Math.min(s.tm_match, 101))}%</span>}
                            {s.qa_count > 0 && <Icons.alert className="size-3 text-warn" aria-label={t("app.jobs.editor.hasQaIssues")} />}
                            {s.comment_threads > 0 && <Icons.note className="size-3" aria-label={t("app.jobs.editor.hasComments")} />}
                            {s.locked && <Icons.key className="size-3" aria-label={t("app.jobs.editor.locked")} />}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </Card>

          {active && (
            <Card className="p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px]">
                <span className="font-semibold">{t("app.jobs.editor.segmentN", { n: active.seq + 1 })}</span>
                <SegmentStateBadge state={active.state} origin={active.origin} />
                <DecisionBadge decision={active.decision} />
                {active.locked && <Badge tone="warn">{t("app.jobs.editor.locked")}</Badge>}
                {active.context && <span className="text-faint">{active.context}</span>}
                {active.max_length && <span className="text-faint">{t("app.jobs.editor.maxLength", { n: active.max_length })}</span>}
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <div className="rounded-md border border-border bg-subtle/50 px-3 py-2 text-[14.5px] leading-relaxed" lang={job.source_lang}>
                  <TaggedText value={active.source_tagged} />
                </div>
                <div>
                  {editable ? (
                    <TagEditor
                      ref={editorRef}
                      value={draft}
                      onChange={setDraft}
                      requiredTags={required}
                      ariaLabel={t("app.jobs.editor.targetEditor")}
                      autoFocus
                    />
                  ) : (
                    <div className="rounded-md border border-border px-3 py-2 text-[14.5px] leading-relaxed">
                      <TaggedText value={active.target_tagged} />
                      <p className="mt-1 text-[12px] text-faint">{t("app.jobs.editor.readOnly")}</p>
                    </div>
                  )}
                </div>
              </div>
              <div className="mt-7 flex flex-wrap items-center gap-2">
                <TagStatus required={required} value={draft} onInsert={editable ? (tok) => editorRef.current?.insertTag(tok) : undefined} />
                <div className="ml-auto flex flex-wrap items-center gap-1.5">
                  {editable && (
                    <Button size="sm" variant="ghost" onClick={() => setDraft(active.source_tagged)} title="Ctrl+Insert">
                      {t("app.jobs.editor.copySource")}
                    </Button>
                  )}
                  {isPm && OPEN_JOB.includes(job.state) && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => void toggleLock()}>
                        {active.locked ? t("app.jobs.editor.unlock") : t("app.jobs.editor.lock")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDialog("split")} disabled={active.locked}>
                        {t("app.jobs.editor.split")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void mergeNext()} disabled={active.locked}>
                        {t("app.jobs.editor.mergeNext")}
                      </Button>
                    </>
                  )}
                  <Button size="sm" variant="primary" loading={saving} disabled={!editable} onClick={() => void confirm()}>
                    <Icons.check className="size-3.5" /> {t("app.jobs.editor.confirm")} <Kbd inverse>Ctrl+Enter</Kbd>
                  </Button>
                </div>
              </div>
            </Card>
          )}
        </div>

        <Card className="flex min-h-[60vh] flex-col overflow-hidden">
          <div role="tablist" aria-label={t("app.jobs.editor.panels")} className="flex flex-wrap gap-1 border-b border-border px-2 py-1.5">
            {(
              [
                ["tm", t("app.jobs.editor.tabTm"), assistData?.tm_matches.length],
                ["terms", t("app.jobs.editor.tabTerms"), assistData?.terms.length],
                ["qa", t("app.jobs.editor.tabQa"), liveCheck?.issues.length],
                ["mt", t("app.jobs.editor.tabMt"), undefined],
                ["concordance", t("app.jobs.editor.tabConcordance"), undefined],
                ["comments", t("app.jobs.editor.tabComments"), active?.comment_threads],
              ] as [Tab, string, number | undefined][]
            ).map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  "rounded-md px-2 py-1 text-[12.5px] font-medium",
                  tab === key ? "bg-accent-subtle text-fg" : "text-muted hover:bg-hover hover:text-fg",
                )}
              >
                {label}
                {count ? <span className="ml-1 tabular text-faint">{count}</span> : null}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 text-[13px]">
            {!active ? (
              <EmptyState title={t("app.jobs.editor.pickSegment")} />
            ) : tab === "tm" ? (
              <TmPanel data={assistData} canUse={editable} onUse={setDraft} />
            ) : tab === "terms" ? (
              <GlossaryPanel data={assistData} />
            ) : tab === "qa" ? (
              <QaPanel data={liveCheck} />
            ) : tab === "mt" ? (
              <MtPanel data={mtData} busy={mtBusy} allowed={isPm} canUse={editable} onFetch={() => void fetchMt()} onUse={setDraft} />
            ) : tab === "concordance" ? (
              <ConcordancePanel job={job} external={concordanceQuery} />
            ) : (
              <CommentsPanel
                key={active.id}
                job={job}
                segmentId={active.id}
                role={role}
                onCount={(n) => patchRow({ id: active.id, comment_threads: n })}
              />
            )}
          </div>
        </Card>
      </div>

      <FindReplaceDialog open={dialog === "find"} job={job} isPm={isPm} onClose={() => setDialog(null)} onApplied={reload} />
      {active && dialog === "split" && (
        <SplitDialog job={job} segment={active} draft={draft} onClose={() => setDialog(null)} onDone={reload} />
      )}
      <PreviewDialog open={dialog === "preview"} job={job} onClose={() => setDialog(null)} />
      <ShortcutsDialog open={dialog === "help"} onClose={() => setDialog(null)} />
    </div>
  );
}
