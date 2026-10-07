"use client";

import { useCallback, useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { TagEditor, TagStatus, tagsValid, type TagEditorHandle } from "@/components/tag-editor";
import { TaggedText } from "@/components/tagged-text";
import { Badge, DecisionBadge, QeBadge, SegmentStateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/input";
import { EmptyState, Kbd, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { humanize } from "@/lib/format";
import { tagsOf } from "@/lib/tags";
import { DECISIONS, SEGMENT_STATES, type Decision, type Job, type ListResponse, type Segment, type SegmentState } from "@/lib/types";

const PAGE = 50;
const APPROVABLE: SegmentState[] = ["translated", "scored", "needs_review", "in_review", "ai_reviewed", "reviewed", "blocked"];

export function SegmentTable({ job, initial }: { job: Job; initial: ListResponse<Segment> }) {
  const toast = useToast();
  const [rows, setRows] = useState(initial.items);
  const [nextOffset, setNextOffset] = useState(initial.next_offset);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<SegmentState | "">("");
  const [decision, setDecision] = useState<Decision | "">("");
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [reporting, setReporting] = useState<Segment | null>(null);
  const delivered = job.state === "delivered";
  const editable = !["delivered", "cancelled", "failed"].includes(job.state);

  const load = useCallback(
    async (q: { state: SegmentState | ""; decision: Decision | ""; offset: number }) => {
      setLoading(true);
      try {
        const res = await api.segments(job.id, { ...q, limit: PAGE });
        setRows(res.items);
        setNextOffset(res.next_offset);
        setOffset(q.offset);
      } catch (e) {
        toast.error("Could not load segments", errorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    [job.id, toast],
  );

  const replace = (s: Segment) => setRows((rs) => rs.map((r) => (r.id === s.id ? s : r)));

  async function approve(seg: Segment) {
    try {
      replace(await api.approveSegment(job.id, seg.id));
      toast.success(`Segment ${seg.seq} approved`);
    } catch (e) {
      toast.error("Approve failed", errorMessage(e));
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="mr-auto text-sm font-semibold">Segments</h2>
        <Select
          aria-label="Filter by state"
          value={state}
          onChange={(e) => {
            const v = e.target.value as SegmentState | "";
            setState(v);
            void load({ state: v, decision, offset: 0 });
          }}
          className="w-40"
        >
          <option value="">All states</option>
          {SEGMENT_STATES.map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter by decision"
          value={decision}
          onChange={(e) => {
            const v = e.target.value as Decision | "";
            setDecision(v);
            void load({ state, decision: v, offset: 0 });
          }}
          className="w-40"
        >
          <option value="">All decisions</option>
          {DECISIONS.map((d) => (
            <option key={d} value={d}>
              {humanize(d)}
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
          title={state || decision ? "No segments match these filters" : "No segments yet"}
          description={state || decision ? "Clear a filter to see more." : "Segments appear once the file has been prepared and translated."}
        />
      ) : (
        <>
        <div className={cn("relative hidden overflow-x-auto md:block", loading && "opacity-60")}>
          <table className="w-full min-w-[860px] border-collapse text-left text-[13.5px]">
            <thead className="border-b border-border bg-subtle/60">
              <tr className="text-[12px] text-muted">
                <th scope="col" className="h-8 w-12 pl-4 font-medium">#</th>
                <th scope="col" className="w-[38%] px-3 font-medium">Source</th>
                <th scope="col" className="px-3 font-medium">Target</th>
                <th scope="col" className="w-16 px-3 font-medium">QE</th>
                <th scope="col" className="w-32 px-3 font-medium">Decision</th>
                <th scope="col" className="w-28 pr-4 text-right font-medium">
                  <span className="sr-only">Actions</span>
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
                  canEdit={editable}
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
              canEdit={editable}
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
          {rows.length > 0 ? `${offset + 1}–${offset + rows.length}` : "0"} {nextOffset === null ? `of ${offset + rows.length}` : ""}
        </span>
        <div className="flex gap-1.5">
          <Button size="sm" disabled={offset === 0 || loading} onClick={() => load({ state, decision, offset: Math.max(0, offset - PAGE) })}>
            Previous
          </Button>
          <Button size="sm" disabled={nextOffset === null || loading} onClick={() => nextOffset !== null && load({ state, decision, offset: nextOffset })}>
            Next
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
  return (
    <tr className={cn("align-top", editing ? "bg-accent-subtle/40" : "hover:bg-subtle/50")}>
      <td className="py-3 pl-4">
        <span className="tabular text-[12.5px] text-faint">{seg.seq}</span>
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
            {seg.reasons.length > 0 && (
              <ul className="mt-1.5 space-y-0.5 text-[12px] text-muted">
                {seg.reasons.map((r, i) => (
                  <li key={i} className="flex gap-1.5">
                    <span className="mt-[7px] size-1 shrink-0 rounded-full bg-faint" aria-hidden="true" />
                    {r}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </td>
      <td className="px-3 py-3">
        <QeBadge value={seg.qe_score} threshold={job.threshold} />
      </td>
      <td className="px-3 py-3">
        <div className="flex flex-col items-start gap-1">
          <DecisionBadge decision={seg.decision} />
          <SegmentStateBadge state={seg.state} />
          {seg.is_control_sample && (
            <Badge tone="info" title="Sampled blind for human control review">
              Control sample
            </Badge>
          )}
        </div>
      </td>
      <td className="py-3 pr-4 text-right">
        {!editing && (
          <div className="flex justify-end gap-1">
            {canEdit && (
              <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Edit segment ${seg.seq}`} title="Edit target">
                <Icons.edit className="size-3.5" />
              </Button>
            )}
            {canEdit && APPROVABLE.includes(seg.state) && (
              <Button size="sm" variant="ghost" onClick={onApprove} aria-label={`Approve segment ${seg.seq}`} title="Approve">
                <Icons.check className="size-3.5" />
              </Button>
            )}
            {canReport && (
              <Button size="sm" variant="ghost" onClick={onReport} aria-label={`Report an error in segment ${seg.seq}`} title="Report an error">
                <Icons.flag className="size-3.5" />
              </Button>
            )}
          </div>
        )}
      </td>
    </tr>
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
  return (
    <li className={cn("space-y-2 px-4 py-3 text-[14px]", editing && "bg-accent-subtle/40")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="tabular mr-1 text-[12.5px] text-faint">#{seg.seq}</span>
        <QeBadge value={seg.qe_score} threshold={job.threshold} />
        <DecisionBadge decision={seg.decision} />
        <SegmentStateBadge state={seg.state} />
        {seg.is_control_sample && <Badge tone="info">Control</Badge>}
      </div>
      <TaggedText value={seg.source_tagged} className="block text-muted" />
      {editing ? (
        <InlineEditor seg={seg} job={job} onDone={onDone} />
      ) : (
        <>
          <TaggedText value={seg.target_tagged} className="block" />
          {seg.reasons.length > 0 && (
            <ul className="space-y-0.5 text-[12px] text-muted">
              {seg.reasons.map((r, i) => (
                <li key={i}>· {r}</li>
              ))}
            </ul>
          )}
          <div className="flex gap-1.5">
            {canEdit && (
              <Button size="sm" onClick={onEdit}>
                <Icons.edit className="size-3.5" /> Edit
              </Button>
            )}
            {canEdit && APPROVABLE.includes(seg.state) && (
              <Button size="sm" onClick={onApprove}>
                <Icons.check className="size-3.5" /> Approve
              </Button>
            )}
            {canReport && (
              <Button size="sm" onClick={onReport}>
                <Icons.flag className="size-3.5" /> Report error
              </Button>
            )}
          </div>
        </>
      )}
    </li>
  );
}

function InlineEditor({ seg, job, onDone }: { seg: Segment; job: Job; onDone: (s?: Segment) => void }) {
  const toast = useToast();
  const editor = useRef<TagEditorHandle>(null);
  const [value, setValue] = useState(seg.target_tagged);
  const [busy, setBusy] = useState(false);
  const required = tagsOf(seg.source_tagged);
  const valid = tagsValid(required, value);
  const changed = value !== seg.target_tagged;

  async function save() {
    if (!valid || !changed) return;
    setBusy(true);
    try {
      const updated = await api.editSegment(job.id, seg.id, value);
      toast.success(`Segment ${seg.seq} saved`, "Your edit counts as a human review.");
      onDone(updated);
    } catch (e) {
      toast.error("Save failed", errorMessage(e));
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
        ariaLabel={`Target for segment ${seg.seq}`}
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
        <TagStatus required={required} value={value} onInsert={(t) => editor.current?.insertTag(t)} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" onClick={save} loading={busy} disabled={!valid || !changed}>
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDone()}>
          Cancel
        </Button>
        <span className="ml-auto flex items-center gap-1 text-[12px] text-faint">
          <Kbd>Ctrl</Kbd>
          <Kbd>Enter</Kbd> save · <Kbd>Esc</Kbd> cancel
        </span>
      </div>
    </div>
  );
}

function ReportDialog({ job, seg, onClose }: { job: Job; seg: Segment | null; onClose: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!seg || !note.trim()) return;
    setBusy(true);
    try {
      await api.reportError(job.id, { segment_id: seg.id, note: note.trim() });
      toast.success("Error reported", "Thanks. It is reviewed and feeds the quality calibration for this language.");
      setNote("");
      onClose();
    } catch (e) {
      toast.error("Could not report", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={seg !== null}
      onClose={onClose}
      title={seg ? `Report an error in segment ${seg.seq}` : "Report an error"}
      description="Tell us what is wrong with the delivered translation. Reported errors are tracked as escaped errors."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} disabled={!note.trim()}>
            Report error
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
          <Field label="What is wrong?">
            {(id) => (
              <Textarea
                id={id}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. The dosage was changed from 0.5 to 5 mL/h."
                required
              />
            )}
          </Field>
        </div>
      )}
    </Dialog>
  );
}
