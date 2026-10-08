"use client";

import { useI18n } from "@/lib/i18n/client";
import { useCallback, useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { TagEditor, TagStatus, tagsValid, type TagEditorHandle } from "@/components/tag-editor";
import { TaggedText } from "@/components/tagged-text";
import { Badge, DecisionBadge, decisionLabel, QeBadge, SegmentStateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/input";
import { EmptyState, Kbd, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { reasonLabel, violationMessages } from "@/lib/reasons";
import { tagsOf } from "@/lib/tags";
import { DECISIONS, SEGMENT_STATES, type Decision, type Job, type ListResponse, type Segment, type SegmentState } from "@/lib/types";

const PAGE = 50;
// routes/jobs.py: only needs_review can be approved; pending/translated/in_review cannot be edited.
const APPROVABLE: SegmentState[] = ["needs_review"];
const NOT_EDITABLE: SegmentState[] = ["pending", "translated", "in_review"];
/** Segments are 0-based in the API; people count from 1. */
const num1 = (seq: number) => seq + 1;

export function SegmentTable({
  job,
  initial,
  initialDecision = "",
  initialState = "",
}: {
  job: Job;
  initial: ListResponse<Segment>;
  initialDecision?: Decision | "";
  initialState?: SegmentState | "";
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState(initial.items);
  const [nextOffset, setNextOffset] = useState(initial.next_offset);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<SegmentState | "">(initialState);
  const [decision, setDecision] = useState<Decision | "">(initialDecision);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [reporting, setReporting] = useState<Segment | null>(null);
  const delivered = job.state === "delivered";
  const editable = !["cancelled", "failed", "merging"].includes(job.state);

  const load = useCallback(
    async (q: { state: SegmentState | ""; decision: Decision | ""; offset: number }) => {
      setLoading(true);
      try {
        const res = await api.segments(job.id, { ...q, limit: PAGE });
        setRows(res.items);
        setNextOffset(res.next_offset);
        setOffset(q.offset);
      } catch (e) {
        toast.error(t("app.jobs.detail.segmentTable.couldNotLoadSegments"), errorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    [job.id, toast, t],
  );

  const replace = (s: Segment) => setRows((rs) => rs.map((r) => (r.id === s.id ? s : r)));

  async function approve(seg: Segment) {
    try {
      replace(await api.approveSegment(job.id, seg.id));
      toast.success(t("app.jobs.detail.segmentTable.segmentApproved", { seq: num1(seg.seq) }));
    } catch (e) {
      toast.error(t("app.jobs.detail.segmentTable.approveFailed"), errorMessage(e));
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="mr-auto text-sm font-semibold">{t("app.jobs.detail.segmentTable.segments")}</h2>
        <Select
          aria-label={t("app.jobs.detail.segmentTable.filterByState")}
          value={state}
          onChange={(e) => {
            const v = e.target.value as SegmentState | "";
            setState(v);
            void load({ state: v, decision, offset: 0 });
          }}
          className="w-40"
        >
          <option value="">{t("app.jobs.detail.segmentTable.allStates")}</option>
          {SEGMENT_STATES.map((s) => (
            <option key={s} value={s}>
              {t.enumLabel(s)}
            </option>
          ))}
        </Select>
        <Select
          aria-label={t("app.jobs.detail.segmentTable.filterByDecision")}
          value={decision}
          onChange={(e) => {
            const v = e.target.value as Decision | "";
            setDecision(v);
            void load({ state, decision: v, offset: 0 });
          }}
          className="w-40"
        >
          <option value="">{t("app.jobs.detail.segmentTable.allDecisions")}</option>
          {DECISIONS.map((d) => (
            <option key={d} value={d}>
              {decisionLabel(t, d)}
            </option>
          ))}
        </Select>
      </div>

      {loading && rows.length === 0 ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          title={state || decision ? t("app.jobs.detail.segmentTable.noSegmentsMatchTheseFilters") : t("app.jobs.detail.segmentTable.noSegmentsYet")}
          description={state || decision ? t("app.jobs.detail.segmentTable.clearAFilterToSee") : t("app.jobs.detail.segmentTable.segmentsAppearOnceTheFile")}
        />
      ) : (
        <>
        <div className={cn("relative hidden overflow-x-auto md:block", loading && "opacity-60")}>
          <table className="w-full min-w-[860px] border-collapse text-left text-[13.5px]">
            <thead className="border-b border-border bg-subtle/60">
              <tr className="text-[12px] text-muted">
                <th scope="col" className="h-8 w-12 pl-4 font-medium">#</th>
                <th scope="col" className="w-[38%] px-3 font-medium">{t("app.jobs.detail.segmentTable.source")}</th>
                <th scope="col" className="px-3 font-medium">{t("app.jobs.detail.segmentTable.target")}</th>
                <th scope="col" className="w-16 px-3 font-medium">{t("app.jobs.detail.segmentTable.qe")}</th>
                <th scope="col" className="w-32 px-3 font-medium">{t("app.jobs.detail.segmentTable.decision")}</th>
                <th scope="col" className="w-28 pr-4 text-right font-medium">
                  <span className="sr-only">{t("app.jobs.detail.segmentTable.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((s) => (
                <SegmentRow
                  key={s.id}
                  seg={s}
                  job={job}
                  editing={editing === s.id}
                  canEdit={editable && !NOT_EDITABLE.includes(s.state)}
                  canReport={delivered || s.state === "delivered"}
                  onEdit={() => setEditing(s.id)}
                  onDone={(updated) => {
                    if (updated) replace(updated);
                    setEditing(null);
                  }}
                  onApprove={() => approve(s)}
                  onReport={() => setReporting(s)}
                />
              ))}
            </tbody>
          </table>
        </div>
        <ul className={cn("divide-y divide-border md:hidden", loading && "opacity-60")}>
          {rows.map((s) => (
            <SegmentCard
              key={s.id}
              seg={s}
              job={job}
              editing={editing === s.id}
              canEdit={editable && !NOT_EDITABLE.includes(s.state)}
              canReport={delivered || s.state === "delivered"}
              onEdit={() => setEditing(s.id)}
              onDone={(updated) => {
                if (updated) replace(updated);
                setEditing(null);
              }}
              onApprove={() => approve(s)}
              onReport={() => setReporting(s)}
            />
          ))}
        </ul>
        </>
      )}

      <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-[12.5px] text-muted">
        <span className="tabular">
          {rows.length === 0 ? "0" : nextOffset === null ? t("app.jobs.detail.segmentTable.rangeOfTotal", { from: offset + 1, to: offset + rows.length, total: offset + rows.length }) : t("app.jobs.detail.segmentTable.range", { from: offset + 1, to: offset + rows.length })}
        </span>
        <div className="flex gap-1.5">
          <Button size="sm" disabled={offset === 0 || loading} onClick={() => load({ state, decision, offset: Math.max(0, offset - PAGE) })}>
            {t("app.jobs.detail.segmentTable.previous")}
          </Button>
          <Button size="sm" disabled={nextOffset === null || loading} onClick={() => nextOffset !== null && load({ state, decision, offset: nextOffset })}>
            {t("app.jobs.detail.segmentTable.next")}
          </Button>
        </div>
      </div>

      <ReportDialog job={job} seg={reporting} onClose={() => setReporting(null)} />
    </Card>
  );
}

function SegmentRow({
  seg,
  job,
  editing,
  canEdit,
  canReport,
  onEdit,
  onDone,
  onApprove,
  onReport,
}: {
  seg: Segment;
  job: Job;
  editing: boolean;
  canEdit: boolean;
  canReport: boolean;
  onEdit: () => void;
  onDone: (s?: Segment) => void;
  onApprove: () => void;
  onReport: () => void;
}) {
  const { t } = useI18n();
  return (
    <tr className={cn("align-top", editing ? "bg-accent-subtle/40" : "hover:bg-subtle/50")}>
      <td className="py-3 pl-4">
        <span className="tabular text-[12.5px] text-faint">{num1(seg.seq)}</span>
      </td>
      <td className="px-3 py-3 leading-relaxed">
        <TaggedText value={seg.source_tagged} />
      </td>
      <td className="px-3 py-3 leading-relaxed">
        {editing ? (
          <InlineEditor seg={seg} job={job} onDone={onDone} />
        ) : (
          <>
            <TaggedText value={seg.target_tagged} />
            <Reasons seg={seg} className="mt-1.5" />
          </>
        )}
      </td>
      <td className="px-3 py-3">
        <QeBadge value={seg.qe_score} threshold={job.threshold} />
      </td>
      <td className="px-3 py-3">
        <div className="flex flex-col items-start gap-1">
          <DecisionBadge decision={seg.decision} />
          <SegmentStateBadge state={seg.state} decision={seg.decision} origin={seg.origin} />
          {seg.is_control_sample && (
            <Badge tone="info" title={t("app.jobs.detail.segmentTable.sampledBlindForHumanControl")}>
              {t("app.jobs.detail.segmentTable.controlSample")}
            </Badge>
          )}
        </div>
      </td>
      <td className="py-3 pr-4 text-right">
        {!editing && (
          <div className="flex justify-end gap-1">
            {canEdit && (
              <Button size="sm" variant="ghost" onClick={onEdit} aria-label={t("app.jobs.detail.segmentTable.editSegment", { seq: num1(seg.seq) })} title={t("app.jobs.detail.segmentTable.editTarget")}>
                <Icons.edit className="size-3.5" />
              </Button>
            )}
            {canEdit && APPROVABLE.includes(seg.state) && (
              <Button size="sm" variant="ghost" onClick={onApprove} aria-label={t("app.jobs.detail.segmentTable.approveSegment", { seq: num1(seg.seq) })} title={t("app.jobs.detail.segmentTable.approve")}>
                <Icons.check className="size-3.5" />
              </Button>
            )}
            {canReport && (
              <Button size="sm" variant="ghost" onClick={onReport} aria-label={t("app.jobs.detail.segmentTable.reportAnErrorInSegment", { seq: num1(seg.seq) })} title={t("app.jobs.detail.segmentTable.reportAnError")}>
                <Icons.flag className="size-3.5" />
              </Button>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}

function Reasons({ seg, className }: { seg: Segment; className?: string }) {
  const { t } = useI18n();
  const lines = [...seg.reasons.map((r) => reasonLabel(t, r)), ...violationMessages(seg.signals)];
  const unique = lines.filter((l, i) => lines.indexOf(l) === i);
  if (unique.length === 0) return null;
  return (
    <ul className={cn("space-y-0.5 text-[12px] text-muted", className)}>
      {unique.map((r, i) => (
        <li key={i} className="flex gap-1.5">
          <span className="mt-[7px] size-1 shrink-0 rounded-full bg-faint" aria-hidden="true" />
          {r}
        </li>
      ))}
    </ul>
  );
}

type RowProps = {
  seg: Segment;
  job: Job;
  editing: boolean;
  canEdit: boolean;
  canReport: boolean;
  onEdit: () => void;
  onDone: (s?: Segment) => void;
  onApprove: () => void;
  onReport: () => void;
};

/** Mobile layout: one stacked card per segment. */
function SegmentCard({ seg, job, editing, canEdit, canReport, onEdit, onDone, onApprove, onReport }: RowProps) {
  const { t } = useI18n();
  return (
    <li className={cn("space-y-2 px-4 py-3 text-[14px]", editing && "bg-accent-subtle/40")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="tabular mr-1 text-[12.5px] text-faint">#{num1(seg.seq)}</span>
        <QeBadge value={seg.qe_score} threshold={job.threshold} />
        <DecisionBadge decision={seg.decision} />
        <SegmentStateBadge state={seg.state} decision={seg.decision} origin={seg.origin} />
        {seg.is_control_sample && <Badge tone="info">{t("app.jobs.detail.segmentTable.control")}</Badge>}
      </div>
      <TaggedText value={seg.source_tagged} className="block text-muted" />
      {editing ? (
        <InlineEditor seg={seg} job={job} onDone={onDone} />
      ) : (
        <>
          <TaggedText value={seg.target_tagged} className="block" />
          <Reasons seg={seg} />
          <div className="flex gap-1.5">
            {canEdit && (
              <Button size="sm" onClick={onEdit}>
                <Icons.edit className="size-3.5" /> {t("app.jobs.detail.segmentTable.edit")}
              </Button>
            )}
            {canEdit && APPROVABLE.includes(seg.state) && (
              <Button size="sm" onClick={onApprove}>
                <Icons.check className="size-3.5" /> {t("app.jobs.detail.segmentTable.approve")}
              </Button>
            )}
            {canReport && (
              <Button size="sm" onClick={onReport}>
                <Icons.flag className="size-3.5" /> {t("app.jobs.detail.segmentTable.reportError")}
              </Button>
            )}
          </div>
        </>
      )}
    </li>
  );
}

function InlineEditor({ seg, job, onDone }: { seg: Segment; job: Job; onDone: (s?: Segment) => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const editor = useRef<TagEditorHandle>(null);
  const [value, setValue] = useState(seg.target_tagged ?? "");
  const [busy, setBusy] = useState(false);
  const required = tagsOf(seg.source_tagged);
  const valid = tagsValid(required, value);
  const changed = value !== (seg.target_tagged ?? "");

  async function save() {
    if (!valid || !changed) return;
    setBusy(true);
    try {
      const updated = await api.editSegment(job.id, seg.id, value);
      toast.success(t("app.jobs.detail.segmentTable.segmentSaved", { seq: num1(seg.seq) }), t("app.jobs.detail.segmentTable.yourEditCountsAsA"));
      onDone(updated);
    } catch (e) {
      toast.error(t("app.jobs.detail.segmentTable.saveFailed"), errorMessage(e));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <TagEditor
        ref={editor}
        value={value}
        onChange={setValue}
        requiredTags={required}
        autoFocus
        ariaLabel={t("app.jobs.detail.segmentTable.targetForSegment", { seq: num1(seg.seq) })}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void save();
          } else if (e.key === "Escape") {
            e.preventDefault();
            onDone();
          }
        }}
      />
      <div className="pt-1">
        <TagStatus required={required} value={value} onInsert={(tag) => editor.current?.insertTag(tag)} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" onClick={save} loading={busy} disabled={!valid || !changed}>
          {t("app.jobs.detail.segmentTable.save")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDone()}>
          {t("app.jobs.detail.segmentTable.cancel")}
        </Button>
        <span className="ml-auto flex items-center gap-1 text-[12px] text-faint">
          <Kbd>{t("app.jobs.detail.segmentTable.ctrl")}</Kbd>
          <Kbd>{t("app.jobs.detail.segmentTable.enter")}</Kbd> {t("app.jobs.detail.segmentTable.save2")} <Kbd>{t("app.jobs.detail.segmentTable.esc")}</Kbd> {t("app.jobs.detail.segmentTable.cancel2")}
        </span>
      </div>
    </div>
  );
}

function ReportDialog({ job, seg, onClose }: { job: Job; seg: Segment | null; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!seg || !note.trim()) return;
    setBusy(true);
    try {
      await api.reportError(job.id, { segment_id: seg.id, note: note.trim() });
      toast.success(t("app.jobs.detail.segmentTable.errorReported"), t("app.jobs.detail.segmentTable.thanksItIsReviewedAnd"));
      setNote("");
      onClose();
    } catch (e) {
      toast.error(t("app.jobs.detail.segmentTable.couldNotReport"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={seg !== null}
      onClose={onClose}
      title={seg ? t("app.jobs.detail.segmentTable.reportAnErrorInSegment", { seq: num1(seg.seq) }) : t("app.jobs.detail.segmentTable.reportAnError")}
      description={t("app.jobs.detail.segmentTable.tellUsWhatIsWrong")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("app.jobs.detail.segmentTable.cancel")}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} disabled={!note.trim()}>
            {t("app.jobs.detail.segmentTable.reportError")}
          </Button>
        </>
      }
    >
      {seg && (
        <div className="space-y-3">
          <div className="rounded-md border border-border bg-subtle/50 p-3 text-[13.5px]">
            <TaggedText value={seg.source_tagged} className="block text-muted" />
            <TaggedText value={seg.target_tagged} className="mt-1.5 block" />
          </div>
          <Field label={t("app.jobs.detail.segmentTable.whatIsWrong")}>
            {(id) => (
              <Textarea
                id={id}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("app.jobs.detail.segmentTable.eGTheDosageWas")}
                required
              />
            )}
          </Field>
        </div>
      )}
    </Dialog>
  );
}
