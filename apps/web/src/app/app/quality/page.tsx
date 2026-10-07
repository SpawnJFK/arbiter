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
  const engines = [...d.engines].sort((a, b) => (b.win_rate ?? 0) - (a.win_rate ?? 0));
  return (
    <>
      <PageHeader
        title="Quality"
        description="How much ships without a human, how much of that later turned out wrong, and where the thresholds sit."
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat tone="ok" label="Auto-approval rate" value={pct(d.auto_rate, 1)} hint="Segments shipped on QE + senate alone" />
        <Stat
          tone={d.escaped_rate > 0.005 ? "danger" : "accent"}
          label="Escaped error rate"
          value={pct(d.escaped_rate, 2)}
          hint="Auto-approved segments later found wrong"
        />
        <Stat label="Control samples" value={num(d.control_samples)} hint="Auto-approved segments reviewed blind by humans" />
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
        <CardHeader title="Engine scoreboard" description="Which engine produced the candidate the senate picked, across your jobs." />
        {engines.length === 0 ? (
          <EmptyState title="No engine data yet" />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Engine</Th>
                <Th className="text-right">Segments</Th>
                <Th className="text-right">Avg QE</Th>
                <Th className="text-right">Auto rate</Th>
                <Th className="text-right">Escaped</Th>
                <Th className="w-56">Selected by senate</Th>
              </tr>
            </THead>
            <TBody>
              {engines.map((e) => (
                <Tr key={e.engine}>
                  <Td className="font-mono text-[13px]">{e.engine}</Td>
                  <Td className="tabular text-right">{num(e.segments ?? null)}</Td>
                  <Td className="tabular text-right">{score(e.avg_qe ?? null)}</Td>
                  <Td className="tabular text-right">{pct(e.auto_rate ?? null)}</Td>
                  <Td className="tabular text-right">{pct(e.escaped_rate ?? null, 2)}</Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
                        <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((e.win_rate ?? 0) * 100)}%` }} />
                      </div>
                      <span className="tabular w-10 text-right text-[12.5px] text-muted">{pct(e.win_rate ?? null)}</span>
                    </div>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
