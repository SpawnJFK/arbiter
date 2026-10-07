import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { langName, num, pct, score } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export const metadata: Metadata = { title: "Quality" };

export default async function QualityPage() {
  const d = await withAuth((api) => api.qualityDashboard(), "/app/quality");
  const engines = d.engines;
  const cs = d.control_samples;
  return (
    <>
      <PageHeader
        title="Quality"
        description="How much ships without a human, how much of that later turned out wrong, and where the thresholds sit."
      />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          tone="ok"
          label="Auto-approval rate"
          value={pct(d.auto_rate, 1)}
          hint={d.segments !== undefined ? `${num(d.auto_approved ?? 0)} of ${num(d.segments)} segments, last ${d.window_days ?? 30} days` : "Segments shipped on QE + senate alone"}
        />
        <Stat
          tone={d.escaped_rate !== null && d.escaped_rate > 0.005 ? "danger" : "accent"}
          label="Escaped error rate"
          value={pct(d.escaped_rate, 2)}
          hint={d.escaped_rate === null ? "No auto-approved segments yet" : `${num(d.escaped_errors ?? 0)} accepted escaped errors`}
        />
        <Stat label="Control samples" value={num(cs.total)} hint={`${num(cs.pending)} pending · ${num(cs.ok)} ok · ${num(cs.escaped)} escaped`} />
        <Stat label="Thresholds" value={num(d.thresholds.length)} hint={`${d.thresholds.filter((t) => t.auto_approval_suspended).length} with auto-approval suspended`} />
      </div>

      <Card className="mb-4">
        <CardHeader
          title="Thresholds"
          description="One per content type and target language. Calibration moves a threshold at most 3 points a week; auto-approval suspends itself when control samples catch errors."
        />
        {d.thresholds.length === 0 ? (
          <EmptyState title="No thresholds yet" description="They are created with your first job in each language." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Content type</Th>
                <Th>Target</Th>
                <Th className="text-right">Threshold</Th>
                <Th className="text-right">Senate band</Th>
                <Th className="text-right">Safety offset</Th>
                <Th>Auto-approval</Th>
              </tr>
            </THead>
            <TBody>
              {d.thresholds.map((t) => (
                <Tr key={t.id}>
                  <Td>{contentTypeLabel(t.content_type)}</Td>
                  <Td>
                    {langName(t.target_lang)} <span className="font-mono text-[12px] text-faint">{t.target_lang}</span>
                  </Td>
                  <Td className="tabular text-right font-medium">{score(t.value)}</Td>
                  <Td className="tabular text-right text-muted">±{score(t.band_width)}</Td>
                  <Td className="tabular text-right text-muted">{t.safety_offset ? `+${score(t.safety_offset)}` : "–"}</Td>
                  <Td>
                    {t.auto_approval_suspended ? (
                      <div>
                        <Badge tone="warn" dot>
                          Suspended
                        </Badge>
                        {t.suspended_reason && <div className="mt-1 text-[12px] text-muted">{t.suspended_reason}</div>}
                      </div>
                    ) : (
                      <Badge tone="ok" dot>
                        Active
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
        <CardHeader title="Engine scoreboard" description="Measured quality per engine for the language pairs you use." />
        {engines.length === 0 ? (
          <EmptyState title="No engine data yet" description="Rows appear once jobs in a language pair have been scored." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Engine</Th>
                <Th>Pair</Th>
                <Th className="hidden md:table-cell">Domain</Th>
                <Th className="text-right">Segments</Th>
                <Th className="text-right">Mean QE</Th>
                <Th className="text-right">Edit distance</Th>
                <Th className="text-right">Term adherence</Th>
              </tr>
            </THead>
            <TBody>
              {engines.map((e) => (
                <Tr key={`${e.engine}-${e.source_lang}-${e.target_lang}-${e.domain ?? ""}`}>
                  <Td className="font-mono text-[13px]">{e.engine}</Td>
                  <Td className="font-mono text-[12.5px] text-muted">
                    {e.source_lang} → {e.target_lang}
                  </Td>
                  <Td className="hidden text-muted md:table-cell">{e.domain ? contentTypeLabel(e.domain) : "All"}</Td>
                  <Td className="tabular text-right">{num(e.segments_measured)}</Td>
                  <Td className="tabular text-right">{score(e.mean_qe)}</Td>
                  <Td className="tabular text-right">{e.mean_edit_distance === null ? "–" : e.mean_edit_distance.toFixed(2)}</Td>
                  <Td className="tabular text-right">{pct(e.term_adherence)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
