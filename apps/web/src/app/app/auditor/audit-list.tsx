"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { EmptyState, Progress } from "@/components/ui/misc";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import type { Glossary } from "@/lib/types";
import type { AiMode, Audit } from "@/lib/types-workbench";

export function AuditStateBadge({ audit }: { audit: Audit }) {
  const { t } = useI18n();
  if (audit.state === "done")
    return <Badge tone={audit.verdict === "pass" ? "ok" : "danger"}>{audit.verdict === "pass" ? t("app.auditor.pass") : t("app.auditor.fail")}</Badge>;
  if (audit.state === "failed") return <Badge tone="danger">{t("app.auditor.failed")}</Badge>;
  return <Badge tone="info">{audit.state === "queued" ? t("app.auditor.queued") : t("app.auditor.running")}</Badge>;
}

export function AuditList({ initial, glossaries, canCreate }: { initial: Audit[]; glossaries: Glossary[]; canCreate: boolean }) {
  const { t, f } = useI18n();
  return (
    <div className="space-y-4">
      {canCreate && <NewAudit glossaries={glossaries} />}
      <Card>
        <CardHeader title={t("app.auditor.audits")} />
        {initial.length === 0 ? (
          <EmptyState title={t("app.auditor.empty")} description={t("app.auditor.emptyHint")} />
        ) : (
          <Table>
            <THead>
              <Tr>
                <Th>{t("app.auditor.name")}</Th>
                <Th>{t("app.auditor.pair")}</Th>
                <Th>{t("app.auditor.input")}</Th>
                <Th>{t("app.auditor.status")}</Th>
                <Th className="text-right">{t("app.auditor.score")}</Th>
                <Th>{t("app.auditor.created")}</Th>
              </Tr>
            </THead>
            <TBody>
              {initial.map((a) => (
                <Tr key={a.id}>
                  <Td>
                    <Link href={`/app/auditor/${a.id}`} className="font-medium hover:underline">
                      {a.name}
                    </Link>
                  </Td>
                  <Td>
                    {a.source_lang} → {a.target_lang}
                  </Td>
                  <Td className="uppercase text-muted">{a.input_format}</Td>
                  <Td>
                    {a.state === "running" || a.state === "queued" ? (
                      <div className="flex min-w-32 items-center gap-2">
                        <Progress value={a.progress} />
                        <span className="tabular text-[12px]">{f.pct(a.progress)}</span>
                      </div>
                    ) : (
                      <AuditStateBadge audit={a} />
                    )}
                  </Td>
                  <Td className="text-right tabular">{a.mqm_score === null ? "–" : f.num(a.mqm_score)}</Td>
                  <Td className="text-muted">
                    <Time iso={a.created_at} mode="relative" />
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function NewAudit({ glossaries }: { glossaries: Glossary[] }) {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState<File | null>(null);
  const [pair, setPair] = useState(false);
  const [name, setName] = useState("");
  const [sl, setSl] = useState("en");
  const [tl, setTl] = useState("de");
  const [glossaryId, setGlossaryId] = useState("");
  const [aiMode, setAiMode] = useState<AiMode>("none");
  const [pct, setPct] = useState("10");
  const [threshold, setThreshold] = useState("");
  const [consistency, setConsistency] = useState(true);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || (pair && !target)) return;
    setBusy(true);
    try {
      const a = await api.createAudit({
        file,
        targetFile: pair ? target : null,
        sourceLang: sl,
        targetLang: tl,
        name: name.trim() || undefined,
        glossaryId: glossaryId || undefined,
        aiMode,
        aiSamplePct: aiMode === "sample" ? Number(pct) : undefined,
        threshold: threshold ? Number(threshold) : null,
        consistency,
      });
      router.push(`/app/auditor/${a.id}`);
    } catch (err) {
      toast.error(t("app.auditor.createFailed"), errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title={t("app.auditor.newAudit")} description={t("app.auditor.newAuditHint")} />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <Checkbox checked={pair} onChange={(e) => setPair(e.target.checked)} label={t("app.auditor.pairMode")} hint={t("app.auditor.pairModeHint")} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={pair ? t("app.auditor.sourceDocument") : t("app.auditor.bilingualFile")} hint={pair ? undefined : t("app.auditor.formats")}>
              {(id) => (
                <input id={id} type="file" accept={pair ? undefined : ".xlf,.xliff,.sdlxliff,.mqxliff,.tmx,.csv,.tsv,.xlsx"} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-[13px]" />
              )}
            </Field>
            {pair && (
              <Field label={t("app.auditor.targetDocument")}>
                {(id) => <input id={id} type="file" onChange={(e) => setTarget(e.target.files?.[0] ?? null)} className="block w-full text-[13px]" />}
              </Field>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label={t("app.auditor.name")}>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
            <Field label={t("app.auditor.sourceLang")}>
              {(id) => (
                <Select id={id} value={sl} onChange={(e) => setSl(e.target.value)}>
                  {LANGS.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("app.auditor.targetLang")}>
              {(id) => (
                <Select id={id} value={tl} onChange={(e) => setTl(e.target.value)}>
                  {LANGS.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("app.auditor.glossary")}>
              {(id) => (
                <Select id={id} value={glossaryId} onChange={(e) => setGlossaryId(e.target.value)}>
                  <option value="">{t("app.auditor.noGlossary")}</option>
                  {glossaries.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label={t("app.auditor.aiJudge")} hint={t("app.auditor.aiJudgeHint")}>
              {(id) => (
                <Select id={id} value={aiMode} onChange={(e) => setAiMode(e.target.value as AiMode)}>
                  <option value="none">{t("app.auditor.aiNone")}</option>
                  <option value="sample">{t("app.auditor.aiSample")}</option>
                  <option value="full">{t("app.auditor.aiFull")}</option>
                </Select>
              )}
            </Field>
            {aiMode === "sample" && (
              <Field label={t("app.auditor.samplePct")}>
                {(id) => <Input id={id} type="number" min={0.5} max={100} step={0.5} value={pct} onChange={(e) => setPct(e.target.value)} />}
              </Field>
            )}
            <Field label={t("app.auditor.threshold")} hint={t("app.auditor.thresholdHint")}>
              {(id) => <Input id={id} type="number" min={0} max={100} step={0.5} value={threshold} onChange={(e) => setThreshold(e.target.value)} />}
            </Field>
            <div className="pt-6">
              <Checkbox checked={consistency} onChange={(e) => setConsistency(e.target.checked)} label={t("app.auditor.consistency")} />
            </div>
          </div>
          <Button type="submit" variant="primary" loading={busy} disabled={!file || (pair && !target)}>
            <Icons.upload className="size-4" /> {t("app.auditor.start")}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
