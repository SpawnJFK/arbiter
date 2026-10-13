"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Scorecard } from "@/components/scorecard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { JobLqa, LqaSettings } from "@/lib/types-workbench";

export function LqaView({ lqa, settings, canEdit }: { lqa: JobLqa; settings: LqaSettings; canEdit: boolean }) {
  const { t } = useI18n();
  return (
    <div className="space-y-4">
      <Scorecard card={lqa} />
      <p className="text-[13px] text-muted">
        {t("app.jobs.lqa.sources", { reviewer: lqa.sources.reviewer, senate: lqa.sources.senate, segments: lqa.segments_with_errors })}
      </p>
      <Card>
        <CardHeader title={t("app.jobs.lqa.errors")} />
        {lqa.errors.length === 0 ? (
          <EmptyState title={t("app.jobs.lqa.noErrors")} description={t("app.jobs.lqa.noErrorsHint")} />
        ) : (
          <Table>
            <THead>
              <Tr>
                <Th>#</Th>
                <Th>{t("app.jobs.lqa.dimension")}</Th>
                <Th>{t("app.jobs.lqa.severity")}</Th>
                <Th>{t("app.jobs.lqa.span")}</Th>
                <Th>{t("app.jobs.lqa.explanation")}</Th>
                <Th>{t("app.jobs.lqa.foundBy")}</Th>
              </Tr>
            </THead>
            <TBody>
              {lqa.errors.map((e, i) => (
                <Tr key={i}>
                  <Td className="tabular">{e.seq}</Td>
                  <Td>{t.enumLabel(e.dimension)}</Td>
                  <Td>
                    <Badge tone={e.severity === "critical" || e.severity === "major" ? "danger" : e.severity === "minor" ? "warn" : "neutral"}>
                      {t.enumLabel(e.severity)}
                    </Badge>
                  </Td>
                  <Td className="max-w-48 truncate">{e.span || "–"}</Td>
                  <Td className="max-w-md">{e.explanation}</Td>
                  <Td className="text-muted">{e.source}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      {canEdit && <LqaSettingsCard initial={settings} />}
    </div>
  );
}

function LqaSettingsCard({ initial }: { initial: LqaSettings }) {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [threshold, setThreshold] = useState(String(initial.threshold));
  const [weights, setWeights] = useState<Record<string, string>>(
    Object.fromEntries(initial.dimensions.map((d) => [d, String(initial.weights[d] ?? 1)])),
  );
  const [busy, setBusy] = useState(false);

  async function save(reset = false) {
    setBusy(true);
    try {
      const res = await api.updateLqaSettings(
        reset
          ? { reset: true }
          : { threshold: Number(threshold), weights: Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, Number(v)])) },
      );
      setThreshold(String(res.threshold));
      setWeights(Object.fromEntries(res.dimensions.map((d) => [d, String(res.weights[d] ?? 1)])));
      toast.success(t("app.jobs.lqa.settingsSaved"));
      router.refresh();
    } catch (e) {
      toast.error(t("app.jobs.lqa.settingsFailed"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title={t("app.jobs.lqa.settings")} description={t("app.jobs.lqa.settingsHint")} />
      <CardBody>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <Field label={t("app.jobs.lqa.passThreshold")} className="max-w-48">
            {(id) => <Input id={id} type="number" min={0} max={100} step={0.5} value={threshold} onChange={(e) => setThreshold(e.target.value)} />}
          </Field>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {initial.dimensions.map((d) => (
              <Field key={d} label={t.enumLabel(d)}>
                {(id) => (
                  <Input
                    id={id}
                    type="number"
                    min={0}
                    max={10}
                    step={0.25}
                    value={weights[d] ?? "1"}
                    onChange={(e) => setWeights((w) => ({ ...w, [d]: e.target.value }))}
                  />
                )}
              </Field>
            ))}
          </div>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" loading={busy}>
              {t("app.jobs.lqa.save")}
            </Button>
            <Button onClick={() => void save(true)} disabled={busy}>
              {t("app.jobs.lqa.reset")}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
