import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.quality.quality") };
}

export default async function QualityPage() {
  const { f, t } = await getI18n();
  const d = await withAuth((api) => api.qualityDashboard(), "/app/quality");
  const engines = d.engines;
  const cs = d.control_samples;
  return (
    <>
      <PageHeader
        title={t("app.quality.quality")}
        description={t("app.quality.howMuchShipsWithoutA")}
      />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          tone="ok"
          label={t("app.quality.autoApprovalRate")}
          value={f.pct(d.auto_rate, 1)}
          hint={d.segments !== undefined ? t("app.quality.ofSegmentsLastDays", { autoApproved: f.num(d.auto_approved ?? 0), segments: f.num(d.segments), days: d.window_days ?? 30 }) : t("app.quality.segmentsShippedOnQeSenate")}
        />
        <Stat
          tone={d.escaped_rate !== null && d.escaped_rate > 0.005 ? "danger" : "accent"}
          label={t("app.quality.escapedErrorRate")}
          value={f.pct(d.escaped_rate, 2)}
          hint={d.escaped_rate === null ? t("app.quality.noAutoApprovedSegmentsYet") : t("app.quality.acceptedEscapedErrors", { count: f.num(d.escaped_errors ?? 0) })}
        />
        <Stat label={t("app.quality.controlSamples")} value={f.num(cs.total)} hint={t("app.quality.pendingOkEscaped", { pending: f.num(cs.pending), ok: f.num(cs.ok), escaped: f.num(cs.escaped) })} />
        <Stat label={t("app.quality.thresholds")} value={f.num(d.thresholds.length)} hint={t("app.quality.withAutoApprovalSuspended", { count: d.thresholds.filter((thr) => thr.auto_approval_suspended).length })} />
      </div>

      <Card className="mb-4">
        <CardHeader
          title={t("app.quality.thresholds")}
          description={t("app.quality.onePerContentTypeAnd")}
        />
        {d.thresholds.length === 0 ? (
          <EmptyState title={t("app.quality.noThresholdsYet")} description={t("app.quality.theyAreCreatedWithYour")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.quality.contentType")}</Th>
                <Th>{t("app.quality.target")}</Th>
                <Th className="text-right">{t("app.quality.threshold")}</Th>
                <Th className="text-right">{t("app.quality.senateBand")}</Th>
                <Th className="text-right">{t("app.quality.safetyOffset")}</Th>
                <Th>{t("app.quality.autoApproval")}</Th>
              </tr>
            </THead>
            <TBody>
              {d.thresholds.map((thr) => (
                <Tr key={thr.id}>
                  <Td>{contentTypeLabel(t, thr.content_type)}</Td>
                  <Td>
                    {f.langName(thr.target_lang)} <span className="font-mono text-[12px] text-faint">{thr.target_lang}</span>
                  </Td>
                  <Td className="tabular text-right font-medium">{f.score(thr.value)}</Td>
                  <Td className="tabular text-right text-muted">±{f.score(thr.band_width)}</Td>
                  <Td className="tabular text-right text-muted">{thr.safety_offset ? `+${f.score(thr.safety_offset)}` : "–"}</Td>
                  <Td>
                    {thr.auto_approval_suspended ? (
                      <div>
                        <Badge tone="warn" dot>
                          {t("app.quality.suspended")}
                        </Badge>
                        {thr.suspended_reason && <div className="mt-1 text-[12px] text-muted">{thr.suspended_reason}</div>}
                      </div>
                    ) : (
                      <Badge tone="ok" dot>
                        {t("app.quality.active")}
                      </Badge>
                    )}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title={t("app.quality.engineScoreboard")} description={t("app.quality.measuredQualityPerEngineFor")} />
        {engines.length === 0 ? (
          <EmptyState title={t("app.quality.noEngineDataYet")} description={t("app.quality.rowsAppearOnceJobsIn")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.quality.engine")}</Th>
                <Th>{t("app.quality.pair")}</Th>
                <Th className="hidden md:table-cell">{t("app.quality.domain")}</Th>
                <Th className="text-right">{t("app.quality.segments")}</Th>
                <Th className="text-right">{t("app.quality.meanQe")}</Th>
                <Th className="text-right">{t("app.quality.editDistance")}</Th>
                <Th className="text-right">{t("app.quality.termAdherence")}</Th>
              </tr>
            </THead>
            <TBody>
              {engines.map((e) => (
                <Tr key={`${e.engine}-${e.source_lang}-${e.target_lang}-${e.domain ?? ""}`}>
                  <Td className="font-mono text-[13px]">{e.engine}</Td>
                  <Td className="font-mono text-[12.5px] text-muted">
                    {e.source_lang} → {e.target_lang}
                  </Td>
                  <Td className="hidden text-muted md:table-cell">{e.domain ? contentTypeLabel(t, e.domain) : t("app.quality.all")}</Td>
                  <Td className="tabular text-right">{f.num(e.segments_measured)}</Td>
                  <Td className="tabular text-right">{f.score(e.mean_qe)}</Td>
                  <Td className="tabular text-right">{e.mean_edit_distance === null ? "–" : e.mean_edit_distance.toFixed(2)}</Td>
                  <Td className="tabular text-right">{f.pct(e.term_adherence)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
