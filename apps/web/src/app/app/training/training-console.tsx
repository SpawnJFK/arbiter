"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useState } from "react";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Stat } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { CustomModel, DatasetPreview, EngineCredential, EngineRegion, Org, TrainingJob, TrainingState } from "@/lib/types";

const PROVIDERS = ["manual", "together", "fireworks"] as const;

const STATE_TONE: Record<TrainingState, Tone> = {
  created: "neutral",
  running: "info",
  evaluating: "violet",
  ready: "ok",
  exported: "accent",
  failed: "danger",
  cancelled: "neutral",
};

export function TrainingConsole({
  org,
  initialJobs,
  initialModels,
  keys,
}: {
  org: Org;
  initialJobs: TrainingJob[];
  initialModels: CustomModel[];
  keys: EngineCredential[];
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [pair, setPair] = useState({ source_lang: "en", target_lang: "", domain: "general" });
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]>("manual");
  const [baseModel, setBaseModel] = useState("");
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [jobs, setJobs] = useState(initialJobs);
  const [models, setModels] = useState(initialModels);
  const [busy, setBusy] = useState<string | null>(null);
  const [registering, setRegistering] = useState<TrainingJob | null | "new">(null);
  const consent = Boolean(org.training_consent);
  const eu = org.processing_region === "eu";

  async function runPreview(e: React.FormEvent) {
    e.preventDefault();
    setBusy("preview");
    try {
      setPreview(await api.trainingPreview(pair));
    } catch (err) {
      toast.error(t("training.couldNotLoad"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function start() {
    setBusy("start");
    try {
      const job = await api.startTraining({ ...pair, provider, base_model: baseModel.trim() });
      setJobs((xs) => [job, ...xs]);
      toast.success(job.state === "exported" ? t("training.exported") : t("training.started"));
    } catch (err) {
      toast.error(t("training.couldNotStart"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function refresh(j: TrainingJob) {
    setBusy(j.id);
    try {
      const updated = await api.refreshTraining(j.id);
      setJobs((xs) => xs.map((x) => (x.id === j.id ? updated : x)));
      if (updated.custom_model_id) setModels((await api.customModels()).items);
    } catch (err) {
      toast.error(t("training.couldNotLoad"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function setActive(m: CustomModel, active: boolean) {
    setBusy(m.id);
    try {
      const updated = active ? await api.activateCustomModel(m.id) : await api.deactivateCustomModel(m.id);
      setModels((xs) => xs.map((x) => (x.id === m.id ? { ...updated, scoreboard: x.scoreboard } : x)));
    } catch (err) {
      toast.error(t("training.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {!consent && (
        <Callout tone="warn" title={t("training.consentTitle")}>
          {t("training.consentBody")}{" "}
          <Link href="/app/settings" className="font-medium text-accent hover:underline">
            {t("training.openSettings")}
          </Link>
        </Callout>
      )}
      {eu && <Callout tone="info">{t("training.euNote")}</Callout>}

      <Card>
        <CardHeader title={t("training.dataset.title")} description={t("training.dataset.description")} />
        <CardBody className="space-y-4">
          <form onSubmit={runPreview} className="grid items-end gap-3 sm:grid-cols-4">
            <Field label={t("training.sourceLang")}>
              {(id) => <Input id={id} required value={pair.source_lang} onChange={(e) => setPair({ ...pair, source_lang: e.target.value.trim() })} />}
            </Field>
            <Field label={t("training.targetLang")}>
              {(id) => <Input id={id} required placeholder="de" value={pair.target_lang} onChange={(e) => setPair({ ...pair, target_lang: e.target.value.trim() })} />}
            </Field>
            <Field label={t("training.domain")}>
              {(id) => <Input id={id} value={pair.domain} onChange={(e) => setPair({ ...pair, domain: e.target.value.trim() || "general" })} />}
            </Field>
            <Button type="submit" loading={busy === "preview"}>
              {t("training.dataset.check")}
            </Button>
          </form>
          {preview && (
            <>
              <div className="grid gap-3 sm:grid-cols-4">
                <Stat label={t("training.dataset.examples")} value={preview.examples} tone={preview.enough ? "ok" : "warn"} />
                <Stat label={t("training.dataset.train")} value={preview.train} hint={t("training.dataset.minimum", { min: preview.min_examples })} />
                <Stat label={t("training.dataset.heldOut")} value={preview.validation} />
                <Stat label={t("training.dataset.estimatedCost")} value={`${preview.estimated_cost[provider] ?? "0.00"} ${preview.currency}`} />
              </div>
              <p className="text-[12.5px] text-muted">
                {t("training.dataset.dropped", { duplicate: preview.dropped.duplicate ?? 0, empty: preview.dropped.empty ?? 0 })}
              </p>
              <div className="grid items-end gap-3 border-t border-border pt-4 sm:grid-cols-3">
                <Field label={t("training.provider")} hint={t(`training.providerHint.${provider}`)}>
                  {(id, d) => (
                    <Select id={id} aria-describedby={d} value={provider} onChange={(e) => setProvider(e.target.value as (typeof PROVIDERS)[number])}>
                      {PROVIDERS.map((p) => (
                        <option key={p} value={p} disabled={eu && p !== "manual"}>
                          {t(`training.providerName.${p}`)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Field label={t("training.baseModel")}>
                  {(id) => <Input id={id} required value={baseModel} onChange={(e) => setBaseModel(e.target.value)} />}
                </Field>
                <Button variant="primary" loading={busy === "start"} disabled={!consent || !preview.enough || !baseModel.trim()} onClick={start}>
                  {t("training.start")}
                </Button>
              </div>
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("training.jobs.title")} />
        {jobs.length === 0 ? (
          <EmptyState title={t("training.jobs.empty")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("training.jobs.pair")}</Th>
                <Th>{t("training.jobs.state")}</Th>
                <Th className="hidden md:table-cell">{t("training.provider")}</Th>
                <Th className="hidden text-right md:table-cell">{t("training.jobs.examples")}</Th>
                <Th className="hidden text-right lg:table-cell">{t("training.jobs.cost")}</Th>
                <Th className="hidden lg:table-cell">{t("training.jobs.created")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("engines.catalog.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {jobs.map((j) => (
                <Tr key={j.id}>
                  <Td>
                    <div className="font-mono text-[12.5px]">
                      {j.source_lang} → {j.target_lang}
                    </div>
                    <div className="text-[12px] text-muted">
                      {j.domain} · {j.base_model}
                    </div>
                  </Td>
                  <Td>
                    <Badge tone={STATE_TONE[j.state]} title={j.error ?? undefined}>
                      {t(`training.state.${j.state}`)}
                    </Badge>
                  </Td>
                  <Td className="hidden md:table-cell">{t(`training.providerName.${j.provider}`)}</Td>
                  <Td className="hidden text-right font-mono tabular-nums md:table-cell">{j.dataset_stats.train ?? 0}</Td>
                  <Td className="hidden text-right font-mono tabular-nums lg:table-cell">
                    {j.cost} {j.currency}
                  </Td>
                  <Td className="hidden text-muted lg:table-cell">
                    <Time iso={j.created_at} mode="relative" />
                  </Td>
                  <Td className="whitespace-nowrap text-right">
                    {j.state === "running" && (
                      <Button size="sm" variant="ghost" loading={busy === j.id} onClick={() => refresh(j)}>
                        {t("training.jobs.refresh")}
                      </Button>
                    )}
                    {j.state === "exported" && (
                      <>
                        <a className="px-2 text-[13px] text-accent hover:underline" href={api.downloadUrl(`/training/jobs/${j.id}/dataset`, { split: "train" })}>
                          {t("training.jobs.downloadTrain")}
                        </a>
                        <Button size="sm" variant="ghost" onClick={() => setRegistering(j)}>
                          {t("training.jobs.registerModel")}
                        </Button>
                      </>
                    )}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader
          title={t("training.models.title")}
          description={t("training.models.description")}
          actions={
            <Button size="sm" onClick={() => setRegistering("new")}>
              {t("training.models.registerExternal")}
            </Button>
          }
        />
        {models.length === 0 ? (
          <EmptyState title={t("training.models.empty")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("training.models.model")}</Th>
                <Th className="hidden md:table-cell">{t("training.models.region")}</Th>
                <Th className="text-right">{t("training.models.meanQe")}</Th>
                <Th className="hidden text-right md:table-cell">{t("training.models.editDistance")}</Th>
                <Th className="hidden text-right lg:table-cell">{t("training.models.measured")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("engines.catalog.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {models.map((m) => (
                <Tr key={m.id}>
                  <Td>
                    <div className="font-medium">{m.name}</div>
                    <div className="font-mono text-[11.5px] text-faint">{m.engine}</div>
                  </Td>
                  <Td className="hidden md:table-cell">
                    <Badge tone={m.region === "eu" ? "ok" : "neutral"}>{t(`engines.region.${m.region}`)}</Badge>
                  </Td>
                  <Td className="text-right font-mono tabular-nums">{m.scoreboard ? m.scoreboard.mean_qe.toFixed(1) : t("training.models.notMeasured")}</Td>
                  <Td className="hidden text-right font-mono tabular-nums md:table-cell">{m.scoreboard ? m.scoreboard.mean_edit_distance.toFixed(3) : ""}</Td>
                  <Td className="hidden text-right font-mono tabular-nums lg:table-cell">{m.scoreboard?.segments_measured ?? 0}</Td>
                  <Td className="text-right">
                    <Button size="sm" variant={m.active ? "ghost" : "secondary"} loading={busy === m.id} onClick={() => setActive(m, !m.active)}>
                      {m.active ? t("training.models.deactivate") : t("training.models.activate")}
                    </Button>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {registering !== null && (
        <RegisterModelDialog
          job={registering === "new" ? null : registering}
          keys={keys}
          defaults={pair}
          eu={eu}
          onClose={() => setRegistering(null)}
          onDone={(m) => {
            setModels((xs) => [m, ...xs]);
            if (m.training_job_id) setJobs((xs) => xs.map((x) => (x.id === m.training_job_id ? { ...x, state: "evaluating" } : x)));
            setRegistering(null);
          }}
        />
      )}
    </div>
  );
}

function RegisterModelDialog({
  job,
  keys,
  defaults,
  eu,
  onClose,
  onDone,
}: {
  job: TrainingJob | null;
  keys: EngineCredential[];
  defaults: { source_lang: string; target_lang: string; domain: string };
  eu: boolean;
  onClose: () => void;
  onDone: (m: CustomModel) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [v, setV] = useState({
    name: "",
    source_lang: job?.source_lang ?? defaults.source_lang,
    target_lang: job?.target_lang ?? defaults.target_lang,
    domain: job?.domain ?? defaults.domain,
    endpoint: "",
    provider_model_id: "",
    credential_id: "",
    region: (eu ? "eu" : "global") as EngineRegion,
  });
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const m = await api.registerCustomModel({ ...v, credential_id: v.credential_id || null, training_job_id: job?.id ?? null });
      toast.success(t("training.models.registered"));
      onDone(m);
    } catch (err) {
      toast.error(t("training.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onClose={onClose} title={t("training.models.registerTitle")} description={t("training.models.registerDescription")}>
      <form onSubmit={save} className="space-y-3">
        <Field label={t("training.models.name")}>{(id) => <Input id={id} required value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("training.sourceLang")}>{(id) => <Input id={id} required value={v.source_lang} onChange={(e) => setV({ ...v, source_lang: e.target.value })} />}</Field>
          <Field label={t("training.targetLang")}>{(id) => <Input id={id} required value={v.target_lang} onChange={(e) => setV({ ...v, target_lang: e.target.value })} />}</Field>
          <Field label={t("training.domain")}>{(id) => <Input id={id} value={v.domain} onChange={(e) => setV({ ...v, domain: e.target.value })} />}</Field>
        </div>
        <Field label={t("engines.field.endpoint")}>
          {(id) => <Input id={id} required type="url" placeholder="https://" value={v.endpoint} onChange={(e) => setV({ ...v, endpoint: e.target.value })} />}
        </Field>
        <Field label={t("training.models.providerModelId")}>
          {(id) => <Input id={id} required value={v.provider_model_id} onChange={(e) => setV({ ...v, provider_model_id: e.target.value })} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("training.models.key")} hint={t("training.models.keyHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={v.credential_id} onChange={(e) => setV({ ...v, credential_id: e.target.value })}>
                <option value="">{t("training.models.noKey")}</option>
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.label} ({k.secret_hint})
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("training.models.region")} hint={t("engines.keys.regionHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={v.region} onChange={(e) => setV({ ...v, region: e.target.value as EngineRegion })}>
                {(["eu", "us", "global"] as const).map((r) => (
                  <option key={r} value={r}>
                    {t(`engines.region.${r}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            {t("engines.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            {t("training.models.register")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
