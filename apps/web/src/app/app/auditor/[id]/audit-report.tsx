"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Scorecard } from "@/components/scorecard";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Callout, EmptyState, Progress } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MQM_SEVERITIES, type Audit, type AuditSegmentPage, type AuditSegmentRow } from "@/lib/types-workbench";

const PAGE = 100;
const DIMENSIONS = [
  "terminology",
  "accuracy",
  "linguistic_conventions",
  "style",
  "locale_conventions",
  "audience_appropriateness",
  "design_and_markup",
  "other",
];

function sevTone(s: string) {
  return s === "critical" || s === "major" ? "danger" : s === "minor" ? "warn" : "neutral";
}

export function AuditReport({ audit, first, canRetry }: { audit: Audit; first: AuditSegmentPage | null; canRetry: boolean }) {
  const { t, f } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  if (audit.state === "queued" || audit.state === "running") {
    return (
      <Card className="p-5">
        <div className="mb-2 flex items-center justify-between text-[13px]">
          <span>{audit.state === "queued" ? t("app.auditor.waiting") : t("app.auditor.checking", { done: audit.segments_done, total: audit.segments_total })}</span>
          <span className="tabular font-medium">{f.pct(audit.progress)}</span>
        </div>
        <Progress value={audit.progress} />
      </Card>
    );
  }
  if (audit.state === "failed") {
    return (
      <Callout tone="danger" title={t("app.auditor.failedTitle")}>
        <p>{audit.error}</p>
        {canRetry && (
          <Button
            className="mt-3"
            size="sm"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.retryAudit(audit.id);
                router.refresh();
              } catch (e) {
                toast.error(t("app.auditor.retryFailed"), errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("app.auditor.retry")}
          </Button>
        )}
      </Callout>
    );
  }
  const s = audit.summary;
  const card = s.scorecard;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <AnchorButton href={api.auditExportUrl(audit.id, "report.pdf")} download>
          <Icons.download className="size-4" /> {t("app.auditor.exportPdf")}
        </AnchorButton>
        <AnchorButton href={api.auditExportUrl(audit.id, "report.xlsx")} download>
          <Icons.download className="size-4" /> {t("app.auditor.exportXlsx")}
        </AnchorButton>
        <AnchorButton href={api.auditExportUrl(audit.id, "annotated.xlf")} download>
          <Icons.download className="size-4" /> {t("app.auditor.exportXliff")}
        </AnchorButton>
      </div>
      {card && <Scorecard card={card} />}
      <Card>
        <CardHeader title={t("app.auditor.summary")} />
        <CardBody className="grid gap-4 text-[13px] sm:grid-cols-3">
          <div>
            <div className="mb-1 font-medium">{t("app.auditor.issuesByCode")}</div>
            <ul className="space-y-0.5">
              {Object.entries(s.issues_by_code ?? {}).map(([code, n]) => (
                <li key={code} className="flex justify-between gap-2">
                  <span>{t.enumLabel(code)}</span>
                  <span className="tabular">{n}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="space-y-1">
            <div className="font-medium">{t("app.auditor.coverage")}</div>
            <p>{t("app.auditor.segmentsWithIssues", { n: s.segments_with_issues ?? 0, total: s.segments ?? audit.segments_total })}</p>
            <p>
              {t("app.auditor.aiCoverage", { mode: s.ai?.mode ?? "none", checked: s.ai?.checked ?? 0, units: audit.ai_units })}
            </p>
            {!!s.ai?.failed && <p className="text-warn">{t("app.auditor.aiFailedCount", { n: s.ai.failed })}</p>}
          </div>
          <div className="space-y-1">
            <div className="font-medium">{t("app.auditor.consistencyTitle")}</div>
            <p>{t("app.auditor.inconsistentTranslations", { n: s.consistency?.inconsistent_translations ?? 0 })}</p>
            <p>{t("app.auditor.inconsistentSources", { n: s.consistency?.inconsistent_sources ?? 0 })}</p>
            {!!s.notes?.unaligned_target_sentences && (
              <p className="text-warn">{t("app.auditor.unaligned", { n: s.notes.unaligned_target_sentences })}</p>
            )}
          </div>
        </CardBody>
      </Card>
      <SegmentsTable audit={audit} first={first} />
    </div>
  );
}

function SegmentsTable({ audit, first }: { audit: Audit; first: AuditSegmentPage | null }) {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<AuditSegmentRow[]>(first?.items ?? []);
  const [total, setTotal] = useState(first?.total ?? 0);
  const [next, setNext] = useState<number | null>(first?.next_offset ?? null);
  const [minSev, setMinSev] = useState("");
  const [dimension, setDimension] = useState("");
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [loading, setLoading] = useState(false);

  async function load(q: { min_severity: string; dimension: string; with_issues: boolean }, offset = 0) {
    setLoading(true);
    try {
      const res = await api.auditSegments(audit.id, {
        min_severity: q.min_severity || undefined,
        dimension: q.dimension || undefined,
        with_issues: q.with_issues || undefined,
        offset,
        limit: PAGE,
      });
      setRows((rs) => (offset === 0 ? res.items : [...rs, ...res.items]));
      setTotal(res.total);
      setNext(res.next_offset);
    } catch (e) {
      toast.error(t("app.auditor.loadFailed"), errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  const q = { min_severity: minSev, dimension, with_issues: onlyIssues };
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h2 className="mr-auto text-sm font-semibold">{t("app.auditor.segments", { n: total })}</h2>
        <Select
          aria-label={t("app.auditor.filterSeverity")}
          className="w-40"
          value={minSev}
          onChange={(e) => {
            setMinSev(e.target.value);
            void load({ ...q, min_severity: e.target.value });
          }}
        >
          <option value="">{t("app.auditor.anySeverity")}</option>
          {MQM_SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {t("app.auditor.atLeast", { severity: t.enumLabel(s) })}
            </option>
          ))}
        </Select>
        <Select
          aria-label={t("app.auditor.filterDimension")}
          className="w-48"
          value={dimension}
          onChange={(e) => {
            setDimension(e.target.value);
            void load({ ...q, dimension: e.target.value });
          }}
        >
          <option value="">{t("app.auditor.anyDimension")}</option>
          {DIMENSIONS.map((d) => (
            <option key={d} value={d}>
              {t.enumLabel(d)}
            </option>
          ))}
        </Select>
        <Button
          size="sm"
          variant={onlyIssues ? "primary" : "secondary"}
          aria-pressed={onlyIssues}
          onClick={() => {
            setOnlyIssues(!onlyIssues);
            void load({ ...q, with_issues: !onlyIssues });
          }}
        >
          {t("app.auditor.onlyIssues")}
        </Button>
      </div>
      {rows.length === 0 ? (
        <EmptyState title={t("app.auditor.noSegments")} />
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((r) => (
            <li key={r.id} className="grid gap-3 px-4 py-3 text-[13.5px] lg:grid-cols-[48px_1fr_1fr_minmax(0,1.2fr)]">
              <div className="flex flex-col gap-1">
                <span className="tabular text-faint">{r.seq + 1}</span>
                {r.max_severity !== "none" && <Badge tone={sevTone(r.max_severity)}>{t.enumLabel(r.max_severity)}</Badge>}
              </div>
              <TaggedText value={r.source_tagged} className="text-muted" />
              <TaggedText value={r.target_tagged || null} />
              <ul className="space-y-1">
                {r.issues.map((i, k) => (
                  <li key={`i${k}`} className={cn("text-[12.5px]", i.blocking ? "text-danger" : "text-fg")}>
                    <Badge tone={sevTone(i.mqm_severity)} className="mr-1.5">
                      {t.enumLabel(i.code)}
                    </Badge>
                    {i.message}
                  </li>
                ))}
                {r.mqm_errors.map((e, k) => (
                  <li key={`m${k}`} className="text-[12.5px]">
                    <Badge tone="accent" className="mr-1.5">
                      {t("app.auditor.ai")} · {t.enumLabel(e.dimension)}
                    </Badge>
                    {e.span && <q className="mr-1">{e.span}</q>}
                    {e.explanation}
                  </li>
                ))}
                {r.issues.length === 0 && r.mqm_errors.length === 0 && <li className="text-[12.5px] text-ok">{t("app.auditor.clean")}</li>}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {next !== null && (
        <div className="border-t border-border px-4 py-3">
          <Button size="sm" loading={loading} onClick={() => void load(q, next)}>
            {t("app.auditor.more")}
          </Button>
        </div>
      )}
    </Card>
  );
}
