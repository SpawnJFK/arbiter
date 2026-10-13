"use client";

import { useI18n } from "@/lib/i18n/client";
import { useMemo, useState } from "react";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { Callout, Kbd } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Job } from "@/lib/types";
import type { EditorSegment, FindReplaceResult } from "@/lib/types-workbench";
import { chunksAt, cutPoints } from "./editor-utils";

export function FindReplaceDialog({
  open,
  job,
  isPm,
  onClose,
  onApplied,
}: {
  open: boolean;
  job: Job;
  isPm: boolean;
  onClose: () => void;
  onApplied: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(false);
  const [scope, setScope] = useState<"target" | "source" | "both">("target");
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<FindReplaceResult | null>(null);
  const [busy, setBusy] = useState(false);

  const body = (apply: boolean) => ({
    find,
    replace: scope === "source" ? null : replace,
    regex,
    case_sensitive: caseSensitive,
    whole_word: wholeWord,
    scope,
    apply,
    force: isPm && force,
  });

  async function run(apply: boolean) {
    if (!find) return;
    setBusy(true);
    try {
      const res = await api.findReplace(job.id, body(apply));
      setResult(res);
      if (apply) {
        toast.success(t("app.jobs.editor.replaced", { changed: res.changed, skipped: res.skipped }));
        onApplied();
      }
    } catch (e) {
      toast.error(t("app.jobs.editor.findFailed"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const skip: Record<string, string> = {
    locked: t("app.jobs.editor.skipLocked"),
    approved: t("app.jobs.editor.skipApproved"),
    state: t("app.jobs.editor.skipState"),
    tag_error: t("app.jobs.editor.skipTagError"),
    unchanged: t("app.jobs.editor.skipUnchanged"),
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t("app.jobs.editor.findReplace")}
      description={t("app.jobs.editor.findReplaceDescription")}
      footer={
        <>
          <Button onClick={() => void run(false)} loading={busy} disabled={!find}>
            {t("app.jobs.editor.previewChanges")}
          </Button>
          <Button variant="primary" onClick={() => void run(true)} loading={busy} disabled={!find || scope === "source" || !result}>
            {t("app.jobs.editor.applyChanges")}
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(false);
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("app.jobs.editor.find")}>
            {(id) => <Input id={id} value={find} onChange={(e) => { setFind(e.target.value); setResult(null); }} autoFocus />}
          </Field>
          <Field label={t("app.jobs.editor.replaceWith")}>
            {(id) => <Input id={id} value={replace} disabled={scope === "source"} onChange={(e) => { setReplace(e.target.value); setResult(null); }} />}
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <Checkbox label={t("app.jobs.editor.regex")} checked={regex} onChange={(e) => { setRegex(e.target.checked); setResult(null); }} />
          <Checkbox label={t("app.jobs.editor.caseSensitive")} checked={caseSensitive} onChange={(e) => { setCaseSensitive(e.target.checked); setResult(null); }} />
          <Checkbox label={t("app.jobs.editor.wholeWord")} checked={wholeWord} onChange={(e) => { setWholeWord(e.target.checked); setResult(null); }} />
          <Select aria-label={t("app.jobs.editor.scope")} className="w-44" value={scope} onChange={(e) => { setScope(e.target.value as "target" | "source" | "both"); setResult(null); }}>
            <option value="target">{t("app.jobs.editor.scopeTarget")}</option>
            <option value="source">{t("app.jobs.editor.scopeSource")}</option>
            <option value="both">{t("app.jobs.editor.scopeBoth")}</option>
          </Select>
          {isPm && <Checkbox label={t("app.jobs.editor.force")} hint={t("app.jobs.editor.forceHint")} checked={force} onChange={(e) => { setForce(e.target.checked); setResult(null); }} />}
        </div>
        <button type="submit" hidden />
      </form>
      {result && (
        <div className="mt-4">
          <p className="mb-2 text-[13px] text-muted">
            {t("app.jobs.editor.matchesSummary", { matches: result.total_matches, segments: result.segments })}
          </p>
          <ul className="max-h-80 divide-y divide-border overflow-y-auto rounded-md border border-border text-[13px]">
            {result.items.map((i) => (
              <li key={i.segment_id} className="grid gap-1 px-3 py-2">
                <div className="flex items-center gap-2 text-[12px] text-faint">
                  <span className="tabular">#{i.seq + 1}</span>
                  {i.skip_reason && <Badge tone="warn">{skip[i.skip_reason]}</Badge>}
                  {result.applied && !i.skip_reason && i.after && <Badge tone="ok">{t("app.jobs.editor.changed")}</Badge>}
                </div>
                {scope !== "target" && i.source_matches > 0 && <TaggedText value={i.source_tagged} className="text-muted" />}
                {i.before && i.target_matches > 0 && <TaggedText value={i.before} className={cn(i.after && "line-through decoration-danger/60")} />}
                {i.after && <TaggedText value={i.after} className="text-ok" />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Dialog>
  );
}

function CutPicker({
  label,
  value,
  cut,
  onCut,
}: {
  label: string;
  value: string;
  cut: number | null;
  onCut: (n: number) => void;
}) {
  const { t } = useI18n();
  const cuts = useMemo(() => cutPoints(value), [value]);
  const chunks = useMemo(() => chunksAt(value, cuts), [value, cuts]);
  return (
    <div>
      <div className="mb-1 text-[12.5px] font-medium">{label}</div>
      <div className="rounded-md border border-border bg-subtle/40 p-2 text-[14px] leading-loose">
        {chunks.map((c, i) => (
          <span key={i}>
            <TaggedText value={c.text} />
            {i < chunks.length - 1 && (
              <button
                type="button"
                onClick={() => onCut(c.end)}
                aria-label={t("app.jobs.editor.cutHere")}
                aria-pressed={cut === c.end}
                className={cn(
                  "mx-0.5 inline-block h-5 w-1.5 translate-y-1 rounded-sm align-baseline",
                  cut === c.end ? "bg-danger" : "bg-border hover:bg-accent",
                )}
              />
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SplitDialog({
  job,
  segment,
  draft,
  onClose,
  onDone,
}: {
  job: Job;
  segment: EditorSegment;
  draft: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [src, setSrc] = useState<number | null>(null);
  const [tgt, setTgt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const target = segment.target_tagged ?? "";
  const unsaved = draft !== target;

  async function submit() {
    if (src === null || (target && tgt === null)) return;
    setBusy(true);
    try {
      await api.splitSegment(job.id, segment.id, { source_offset: src, target_offset: target ? tgt : null });
      toast.success(t("app.jobs.editor.splitDone"));
      onDone();
      onClose();
    } catch (e) {
      toast.error(t("app.jobs.editor.splitFailed"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={t("app.jobs.editor.splitTitle", { n: segment.seq + 1 })}
      description={t("app.jobs.editor.splitDescription")}
      footer={
        <Button variant="primary" loading={busy} disabled={src === null || (!!target && tgt === null)} onClick={() => void submit()}>
          {t("app.jobs.editor.split")}
        </Button>
      }
    >
      <div className="space-y-4">
        {unsaved && <Callout tone="warn">{t("app.jobs.editor.splitUnsaved")}</Callout>}
        <CutPicker label={t("app.jobs.editor.source")} value={segment.source_tagged} cut={src} onCut={setSrc} />
        {target && <CutPicker label={t("app.jobs.editor.target")} value={target} cut={tgt} onCut={setTgt} />}
      </div>
    </Dialog>
  );
}

export function PreviewDialog({ open, job, onClose }: { open: boolean; job: Job; onClose: () => void }) {
  const { t } = useI18n();
  const [n, setN] = useState(0);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t("app.jobs.editor.previewTitle")}
      description={t("app.jobs.editor.previewDescription")}
      footer={<Button onClick={() => setN((x) => x + 1)}>{t("app.jobs.editor.refresh")}</Button>}
    >
      {open && (
        <iframe
          key={n}
          title={t("app.jobs.editor.previewTitle")}
          src={`${api.previewUrl(job.id)}?v=${n}`}
          sandbox=""
          className="h-[60vh] w-full rounded-md border border-border bg-white"
        />
      )}
    </Dialog>
  );
}

const SHORTCUTS: [string, string][] = [
  ["Ctrl+Enter", "app.jobs.editor.keyConfirm"],
  ["Ctrl+↓ / Ctrl+↑", "app.jobs.editor.keyMove"],
  ["Ctrl+Shift+F", "app.jobs.editor.keyFind"],
  ["Ctrl+K", "app.jobs.editor.keyConcordance"],
  ["Ctrl+M", "app.jobs.editor.keyMt"],
  ["Ctrl+1 / 2 / 3", "app.jobs.editor.keyTm"],
  ["Ctrl+Insert", "app.jobs.editor.keyCopySource"],
  ["Esc", "app.jobs.editor.keyClose"],
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onClose={onClose} size="sm" title={t("app.jobs.editor.shortcuts")}>
      <ul className="space-y-2 text-[13px]">
        {SHORTCUTS.map(([keys, label]) => (
          <li key={keys} className="flex items-center justify-between gap-3">
            <span>{t(label)}</span>
            <Kbd>{keys}</Kbd>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
