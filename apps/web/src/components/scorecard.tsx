"use client";

import { useI18n } from "@/lib/i18n/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { MQM_SEVERITIES, type LqaCard } from "@/lib/types-workbench";

/** MQM scorecard: verdict, score vs threshold, dimension x severity table. Shared by job LQA and the auditor. */
export function Scorecard({ card, title }: { card: LqaCard; title?: string }) {
  const { t, f } = useI18n();
  const dims = Object.keys(card.by_dimension);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          tone={card.passed ? "ok" : "danger"}
          label={t("components.scorecard.verdict")}
          value={card.passed ? t("components.scorecard.pass") : t("components.scorecard.fail")}
          hint={t("components.scorecard.threshold", { threshold: f.num(card.threshold) })}
        />
        <Stat label={t("components.scorecard.score")} value={f.num(card.score)} hint={t("components.scorecard.per100Words")} />
        <Stat label={t("components.scorecard.errors")} value={f.num(card.error_count)} hint={t("components.scorecard.penalty", { penalty: f.num(card.penalty) })} />
        <Stat label={t("components.scorecard.words")} value={f.num(card.word_count)} />
      </div>
      <Card>
        <CardHeader title={title ?? t("components.scorecard.byDimension")} />
        <Table>
          <THead>
            <Tr>
              <Th>{t("components.scorecard.dimension")}</Th>
              {MQM_SEVERITIES.map((s) => (
                <Th key={s} className="text-right">
                  {t.enumLabel(s)}
                </Th>
              ))}
              <Th className="text-right">{t("components.scorecard.weight")}</Th>
              <Th className="text-right">{t("components.scorecard.penaltyCol")}</Th>
            </Tr>
          </THead>
          <TBody>
            {dims.map((d) => {
              const c = card.by_dimension[d];
              const any = MQM_SEVERITIES.some((s) => c[s] > 0);
              return (
                <Tr key={d} className={any ? undefined : "text-faint"}>
                  <Td>{t.enumLabel(d)}</Td>
                  {MQM_SEVERITIES.map((s) => (
                    <Td key={s} className="text-right tabular">
                      {c[s] > 0 ? <Badge tone={s === "critical" || s === "major" ? "danger" : s === "minor" ? "warn" : "neutral"}>{c[s]}</Badge> : "0"}
                    </Td>
                  ))}
                  <Td className="text-right tabular">{card.weights[d] ?? 1}</Td>
                  <Td className="text-right tabular">{f.num(c.penalty)}</Td>
                </Tr>
              );
            })}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
