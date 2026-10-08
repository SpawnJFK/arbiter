"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Translator } from "@/lib/i18n/core";
import { CONTENT_TYPES, contentTypeLabel, LANGS } from "@/lib/langs";
import { TIERS, type Account, type Quote, type Tier, type UploadedFile, type Workflow } from "@/lib/types";
import { WorkflowPipeline } from "@/components/workflow-pipeline";

const STEPS = ["file", "languages", "quote", "confirm"] as const;

export function NewProjectWizard({
  defaultTier,
  regulated,
  vertical,
  accounts = [],
  workflows = [],
  initialAccountId = "",
}: {
  defaultTier: Tier;
  regulated: boolean;
  vertical: string | null;
  accounts?: Account[];
  workflows?: Workflow[];
  initialAccountId?: string;
}) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [sourceLang, setSourceLang] = useState("en");
  const [name, setName] = useState("");
  const [uploaded, setUploaded] = useState<UploadedFile | null>(null);

  const [targets, setTargets] = useState<string[]>([]);
  const [contentType, setContentType] = useState(regulated ? "regulatory" : "general");
  const [langFilter, setLangFilter] = useState("");

  const initialAccount = accounts.find((a) => a.id === initialAccountId);
  const [accountId, setAccountId] = useState(initialAccountId);
  const [workflowId, setWorkflowId] = useState(initialAccount?.workflow_template_id ?? "");
  const account = accounts.find((a) => a.id === accountId);
  const workflow = workflows.find((w) => w.id === workflowId);
  function chooseAccount(id: string) {
    setAccountId(id);
    const a = accounts.find((x) => x.id === id);
    setWorkflowId(a?.workflow_template_id ?? "");
  }

  const [quote, setQuote] = useState<Quote | null>(null);
  const [tier, setTier] = useState<Tier | null>(null);
  const [dueAt, setDueAt] = useState("");

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const doUpload = () =>
    run(async () => {
      if (!file) throw new Error(t("app.projects.new.wizard.chooseAFileFirst"));
      const uploadedFile = await api.uploadFile(file, sourceLang);
      setUploaded(uploadedFile);
      if (!name) setName(file.name.replace(/\.[^.]+$/, ""));
      setTargets((prev) => prev.filter((x) => x !== sourceLang));
      setStep(1);
    });

  const doQuote = () =>
    run(async () => {
      if (!uploaded) return;
      if (targets.length === 0) throw new Error(t("app.projects.new.wizard.pickAtLeastOneTarget"));
      const q = await api.createQuote({ file_id: uploaded.id, target_langs: targets, content_type: contentType, account_id: accountId || undefined });
      setQuote(q);
      const wanted = workflow?.tier ?? account?.default_tier ?? defaultTier;
      const preferred = q.tiers[wanted]?.available ? wanted : TIERS.find((tier) => q.tiers[tier]?.available) ?? null;
      setTier(preferred);
      setStep(2);
    });

  const doCreate = () =>
    run(async () => {
      if (!quote || !tier) return;
      const project = await api.createProject({
        name: name.trim() || uploaded?.filename || "Untitled project",
        quote_id: quote.id,
        // A workflow template sets the tier itself (routes/projects.py _resolve_workflow).
        ...(workflow ? { workflow_template_id: workflow.id } : { tier }),
        account_id: accountId || undefined,
        due_at: dueAt ? new Date(dueAt).toISOString() : undefined,
      });
      toast.success(t("app.projects.new.wizard.projectStarted"), t("app.projects.new.wizard.jobsQueued", { count: project.target_langs.length }));
      router.push(`/app/projects/${project.id}`);
      router.refresh();
    });

  return (
    <div className="space-y-4">
      <Stepper step={step} onJump={(i) => i < step && setStep(i)} />
      {error && <Callout tone="danger">{error}</Callout>}

      {step === 0 && (
        <Card className="p-5">
          <div className="grid gap-5 md:grid-cols-[1.3fr_1fr]">
            <FileDrop file={file} onFile={setFile} />
            <div className="space-y-4">
              <Field label={t("app.projects.new.wizard.projectName")} hint={t("app.projects.new.wizard.defaultsToTheFileName")}>
                {(id, d) => <Input id={id} aria-describedby={d} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("app.projects.new.wizard.eGIfuV43")} />}
              </Field>
              {accounts.length > 0 && (
                <Field label={t("app.projects.new.wizard.account")} hint={account ? accountHint(t, account, workflows) : t("app.projects.new.wizard.accountOptionalHint")}>
                  {(id, d) => (
                    <Select id={id} aria-describedby={d} value={accountId} onChange={(e) => chooseAccount(e.target.value)}>
                      <option value="">{t("app.projects.new.wizard.noAccount")}</option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              )}
              <Field label={t("app.projects.new.wizard.sourceLanguage")}>
                {(id) => (
                  <Select id={id} value={sourceLang} onChange={(e) => setSourceLang(e.target.value)}>
                    {LANGS.map((l) => (
                      <option key={l} value={l}>
                        {f.langName(l)} ({l})
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          </div>
          <div className="mt-5 flex justify-end">
            <Button variant="primary" onClick={doUpload} loading={busy} disabled={!file}>
              {t("app.projects.new.wizard.uploadAndContinue")}
            </Button>
          </div>
        </Card>
      )}

      {step === 1 && uploaded && (
        <Card className="p-5">
          <FileSummary file={uploaded} sourceLang={sourceLang} />
          <div className="mt-5 grid gap-5 md:grid-cols-[1.4fr_1fr]">
            <fieldset>
              <div className="mb-2 flex items-end justify-between gap-3">
                <legend className="text-[13px] font-medium">
                  {t("app.projects.new.wizard.targetLanguages")} <span className="font-normal text-muted">{t("app.projects.new.wizard.selected", { count: targets.length })}</span>
                </legend>
                <Input
                  aria-label={t("app.projects.new.wizard.filterLanguages")}
                  placeholder={t("app.projects.new.wizard.filter")}
                  value={langFilter}
                  onChange={(e) => setLangFilter(e.target.value)}
                  className="h-7 max-w-40 text-[13px]"
                />
              </div>
              <div className="grid max-h-64 grid-cols-2 gap-1 overflow-y-auto rounded-md border border-border p-1.5 sm:grid-cols-3">
                {LANGS.filter((l) => l !== sourceLang)
                  .filter((l) => !langFilter || `${l} ${f.langName(l)}`.toLowerCase().includes(langFilter.toLowerCase()))
                  .map((l) => {
                    const on = targets.includes(l);
                    return (
                      <label
                        key={l}
                        className={cn(
                          "flex h-8 cursor-pointer items-center gap-2 rounded px-2 text-[13px]",
                          on ? "bg-accent-subtle text-accent" : "hover:bg-hover",
                        )}
                      >
                        <input
                          type="checkbox"
                          className="accent-[var(--accent)]"
                          checked={on}
                          onChange={() => setTargets(on ? targets.filter((x) => x !== l) : [...targets, l])}
                        />
                        <span className="truncate">{f.langName(l)}</span>
                        <span className="ml-auto font-mono text-[11px] text-faint">{l}</span>
                      </label>
                    );
                  })}
              </div>
            </fieldset>
            <div className="space-y-4">
              <Field label={t("app.projects.new.wizard.contentType")} hint={t("app.projects.new.wizard.setsTheQualityThresholdAnd")}>
                {(id, d) => (
                  <Select id={id} aria-describedby={d} value={contentType} onChange={(e) => setContentType(e.target.value)}>
                    {CONTENT_TYPES.map((c) => (
                      <option key={c.value} value={c.value}>
                        {contentTypeLabel(t, c.value)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {regulated && (
                <Callout tone="info" title={t("app.projects.new.wizard.regulatedOrganisation")}>
                  {vertical ? t("app.projects.new.wizard.regulatedVerticalNotice", { vertical: t.enumLabel(vertical) }) : t("app.projects.new.wizard.regulatedNotice")}
                </Callout>
              )}
            </div>
          </div>
          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(0)}>
              {t("app.projects.new.wizard.back")}
            </Button>
            <Button variant="primary" onClick={doQuote} loading={busy} disabled={targets.length === 0}>
              {t("app.projects.new.wizard.getQuote")}
            </Button>
          </div>
        </Card>
      )}

      {step === 2 && quote && (
        <QuoteStep
          quote={quote}
          tier={workflow ? workflow.tier : tier}
          onTier={setTier}
          workflows={workflows}
          workflowId={workflowId}
          onWorkflow={(id) => {
            setWorkflowId(id);
            const w = workflows.find((x) => x.id === id);
            if (w) setTier(w.tier);
          }}
          accountName={account?.name}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
        />
      )}

      {step === 3 && quote && tier && uploaded && (
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold">{t("app.projects.new.wizard.confirmAndStart")}</h2>
          <dl className="mt-4 grid gap-x-8 gap-y-3 text-[13.5px] sm:grid-cols-2">
            <Row k={t("app.projects.new.wizard.rowProject")} v={name || uploaded.filename} />
            <Row k={t("app.projects.new.wizard.rowFile")} v={t("app.projects.new.wizard.fileSummary", { filename: uploaded.filename, words: f.num(uploaded.word_count) })} />
            <Row k={t("app.projects.new.wizard.rowLanguages")} v={`${quote.source_lang} → ${quote.target_langs.join(", ")}`} />
            <Row k={t("app.projects.new.wizard.rowContentType")} v={contentTypeLabel(t, quote.content_type)} />
            {account && <Row k={t("app.projects.new.wizard.rowAccount")} v={account.name} />}
            <Row k={t("app.projects.new.wizard.rowWorkflow")} v={workflow ? workflow.name : t("app.projects.new.wizard.tierDefault", { tier: t(`tier.${tier}.label`) })} />
            <Row k={t("app.projects.new.wizard.rowTier")} v={t(`tier.${tier}.label`)} />
            <Row k={t("app.projects.new.wizard.rowPrice")} v={f.money(quote.tiers[tier].price, quote.currency)} />
            <Row k={t("app.projects.new.wizard.rowExpectedAuto")} v={f.pct(quote.tiers[tier].est_auto_rate)} />
            <Row k={t("app.projects.new.wizard.rowDelivery")} v={f.hours(quote.tiers[tier].eta_hours)} />
          </dl>
          <div className="mt-5 max-w-xs">
            <Field label={t("app.projects.new.wizard.dueDateOptional")} hint={t("app.projects.new.wizard.weAlertYouIfThe")}>
              {(id, d) => <Input id={id} aria-describedby={d} type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />}
            </Field>
          </div>
          {(tier === "hybrid" || tier === "full") && (
            <Callout tone="info" className="mt-5">
              {t("app.projects.new.wizard.segmentsThatNeedAHuman")}
            </Callout>
          )}
          {regulated && (
            <Callout tone="warn" className="mt-3" title={t("app.projects.new.wizard.regulatedContent")}>
              {t("app.projects.new.wizard.everyShippedSegmentWillCarry")}
            </Callout>
          )}
          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>
              {t("app.projects.new.wizard.back")}
            </Button>
            <Button variant="primary" onClick={doCreate} loading={busy}>
              {t("app.projects.new.wizard.startProject", { price: f.money(quote.tiers[tier].price, quote.currency) })}
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border pb-2">
      <dt className="text-muted">{k}</dt>
      <dd className="text-right font-medium">{v}</dd>
    </div>
  );
}

function Stepper({ step, onJump }: { step: number; onJump: (i: number) => void }) {
  const { t } = useI18n();
  return (
    <ol className="flex items-center gap-2 overflow-x-auto text-[13px]" aria-label={t("app.projects.new.wizard.progress")}>
      {STEPS.map((s, i) => (
        <li key={t(`app.projects.new.wizard.step.${s}`)} className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onJump(i)}
            disabled={i >= step}
            aria-current={i === step ? "step" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-full py-1 pl-1 pr-3 transition-colors",
              i === step ? "bg-surface font-medium text-fg shadow-card ring-1 ring-border" : i < step ? "text-muted hover:text-fg" : "text-faint",
            )}
          >
            <span
              className={cn(
                "flex size-5 items-center justify-center rounded-full text-[11px] font-semibold",
                i < step ? "bg-ok text-white" : i === step ? "bg-accent text-accent-fg" : "bg-subtle text-faint",
              )}
            >
              {i < step ? <Icons.check className="size-3" /> : i + 1}
            </span>
            {s}
          </button>
          {i < STEPS.length - 1 && <span className="h-px w-6 bg-border-strong" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

function FileDrop({ file, onFile }: { file: File | null; onFile: (value: File) => void }) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const picked = e.dataTransfer.files?.[0];
        if (picked) onFile(picked);
      }}
      className={cn(
        "flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center transition-colors",
        over ? "border-accent bg-accent-subtle" : "border-border-strong bg-subtle/40",
      )}
    >
      <Icons.upload className="size-6 text-faint" />
      {file ? (
        <>
          <p className="mt-2 font-medium">{file.name}</p>
          <p className="text-[12.5px] text-muted">{t("app.projects.new.wizard.kb", { value: (file.size / 1024).toFixed(0) })}</p>
        </>
      ) : (
        <>
          <p className="mt-2 font-medium">{t("app.projects.new.wizard.dropAFileHere")}</p>
          <p className="text-[12.5px] text-muted">{t("app.projects.new.wizard.docxXlsxPptxHtmlMarkdown")}</p>
        </>
      )}
      <label className="mt-3">
        <span className="sr-only">{t("app.projects.new.wizard.chooseFile")}</span>
        <input
          ref={input}
          type="file"
          name="file"
          className="sr-only"
          accept=".docx,.xlsx,.pptx,.html,.htm,.md,.json,.po,.xlf,.xliff,.txt"
          onChange={(e) => {
            const picked = e.target.files?.[0];
            if (picked) onFile(picked);
          }}
        />
        <Button size="sm" onClick={() => input.current?.click()}>
          {file ? t("app.projects.new.wizard.chooseAnotherFile") : t("app.projects.new.wizard.chooseFile")}
        </Button>
      </label>
    </div>
  );
}

function FileSummary({ file: up, sourceLang }: { file: UploadedFile; sourceLang: string }) {
  const { f, t } = useI18n();
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13.5px]">
        <span className="font-medium">{up.filename}</span>
        <Badge>{up.format.toUpperCase()}</Badge>
        <span className="text-muted">{f.langName(sourceLang)}</span>
        <span className="tabular text-muted">{t("app.projects.new.wizard.segments", { segment_count: f.num(up.segment_count) })}</span>
        <span className="tabular text-muted">{t("app.projects.new.wizard.words", { word_count: f.num(up.word_count) })}</span>
      </div>
      {up.warnings.length > 0 && (
        <Callout tone="warn" className="mt-3" title={t("app.projects.new.wizard.fileWarnings")}>
          <ul className="list-disc pl-4">
            {up.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Callout>
      )}
    </div>
  );
}

function accountHint(t: Translator, a: Account, workflows: Workflow[]): string {
  const w = workflows.find((x) => x.id === a.workflow_template_id);
  const parts = [
    w ? t("app.projects.new.wizard.hintWorkflow", { name: w.name }) : a.default_tier ? t("app.projects.new.wizard.hintTier", { tier: t(`tier.${a.default_tier}.label`) }) : t("app.projects.new.wizard.hintOrgDefaults"),
    a.price_list_id ? t("app.projects.new.wizard.hintOwnPriceList") : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

function QuoteStep({
  quote,
  tier,
  onTier,
  onBack,
  onNext,
  workflows,
  workflowId,
  onWorkflow,
  accountName,
}: {
  quote: Quote;
  tier: Tier | null;
  onTier: (item: Tier) => void;
  onBack: () => void;
  onNext: () => void;
  workflows: Workflow[];
  workflowId: string;
  onWorkflow: (id: string) => void;
  accountName?: string;
}) {
  const { f, t } = useI18n();
  const workflow = workflows.find((w) => w.id === workflowId);
  const a = quote.analysis;
  const parts = useMemo(
    () => [
      { k: t("app.projects.new.wizard.tmContext"), v: a.tm_context, c: "bg-ok" },
      { k: t("app.projects.new.wizard.tmExact"), v: a.tm_exact, c: "bg-ok/70" },
      { k: t("app.projects.new.wizard.tmFuzzy"), v: a.tm_fuzzy, c: "bg-info" },
      { k: t("app.projects.new.wizard.tmRepetitions"), v: a.repetitions, c: "bg-violet" },
      { k: t("app.projects.new.wizard.tmNew"), v: a.new, c: "bg-border-strong" },
    ],
    [a, t],
  );
  const total = parts.reduce((n, p) => n + p.v, 0) || 1;

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[15px] font-semibold">
            {t("app.projects.new.wizard.words2", { word_count: f.num(quote.word_count), source_lang: quote.source_lang, value: quote.target_langs.join(", ") })}
          </h2>
          <span className="text-[12.5px] text-muted">{t("app.projects.new.wizard.quoteValidUntil", { valid_until: f.dateTime(quote.valid_until) })}</span>
        </div>
        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-subtle" aria-hidden="true">
          {parts.map((p) => (
            <div key={p.k} className={p.c} style={{ width: `${(p.v / total) * 100}%` }} />
          ))}
        </div>
        <ul className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-muted">
          {parts.map((p) => (
            <li key={p.k} className="flex items-center gap-1.5">
              <span className={cn("size-2 rounded-full", p.c)} aria-hidden="true" />
              {p.k} <span className="tabular font-medium text-fg">{f.num(p.v)}</span>
            </li>
          ))}
        </ul>
      </Card>

      {workflows.length > 0 && (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <label className="block min-w-64 flex-1 text-[13px] font-medium sm:max-w-sm">
              {t("app.projects.new.wizard.workflow")}
              <Select className="mt-1" aria-label={t("app.projects.new.wizard.workflow")} value={workflowId} onChange={(e) => onWorkflow(e.target.value)}>
                <option value="">{t("app.projects.new.wizard.noneUseTheTierYou")}</option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id} disabled={!quote.tiers[w.tier]?.available}>
                    {w.name} ({t(`tier.${w.tier}.label`)})
                  </option>
                ))}
              </Select>
            </label>
            {accountName && <p className="pb-2 text-[12.5px] text-muted">{t("app.projects.new.wizard.pricesFromSPriceList", { accountName: accountName })}</p>}
          </div>
          {workflow && (
            <>
              <WorkflowPipeline steps={workflow.steps} compact className="mt-3" />
              <p className="mt-2 text-[12.5px] text-muted">{t("app.projects.new.wizard.theWorkflowSetsTheTier", { tier: t(`tier.${workflow.tier}.label`) })}</p>
            </>
          )}
        </Card>
      )}

      <div role="radiogroup" aria-label={t("app.projects.new.wizard.serviceTier")} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {TIERS.map((option) => {
          const q = quote.tiers[option];
          if (!q) return null;
          const selected = tier === option;
          return (
            <label
              key={option}
              className={cn(
                "relative flex flex-col rounded-lg border bg-surface p-4 shadow-card transition-colors",
                q.available ? "cursor-pointer hover:border-faint" : "cursor-not-allowed bg-subtle/50",
                selected ? "border-accent ring-1 ring-accent" : "border-border",
              )}
            >
              <input
                type="radio"
                name="tier"
                value={option}
                className="sr-only"
                checked={selected}
                disabled={!q.available || (workflow !== undefined && workflow.tier !== option)}
                onChange={() => onTier(option)}
                aria-describedby={`tier-${option}-desc`}
              />
              <div className="flex items-center justify-between">
                <span className={cn("font-semibold", !q.available && "text-muted")}>{t(`tier.${option}.label`)}</span>
                {!q.available ? (
                  <Badge tone="warn">{t("app.projects.new.wizard.notAvailable")}</Badge>
                ) : selected ? (
                  <span className="flex size-4.5 items-center justify-center rounded-full bg-accent text-accent-fg">
                    <Icons.check className="size-3" />
                  </span>
                ) : (
                  <span className={cn("size-4.5 rounded-full border border-border-strong", !q.available && "opacity-40")} />
                )}
              </div>
              <div className={cn("tabular mt-3 text-2xl font-semibold tracking-tight", !q.available && "text-faint line-through decoration-1")}>
                {f.money(q.price, quote.currency)}
              </div>
              <dl className="mt-3 space-y-1.5 text-[13px]">
                <div className="flex justify-between">
                  <dt className="text-muted">{t("app.projects.new.wizard.estAutoApproval")}</dt>
                  <dd className="tabular font-medium">{f.pct(q.est_auto_rate)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">{t("app.projects.new.wizard.deliveryEstimate")}</dt>
                  <dd className="tabular font-medium">{f.hours(q.eta_hours)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">{t("app.projects.new.wizard.humanReview")}</dt>
                  <dd className="font-medium">{option === "full" ? t("app.projects.new.wizard.everySegment") : option === "hybrid" ? t("app.projects.new.wizard.belowThreshold") : t("app.projects.new.wizard.none")}</dd>
                </div>
              </dl>
              <p id={`tier-${option}-desc`} className="mt-3 border-t border-border pt-3 text-[12.5px] leading-relaxed text-muted">
                {q.available ? t(`tier.${option}.blurb`) : <span className="text-warn">{q.blocked_reason ?? t("app.projects.new.wizard.notAvailableForThisProject")}</span>}
              </p>
            </label>
          );
        })}
      </div>
      <p className="text-[12.5px] text-muted">
        {t("app.projects.new.wizard.autoApprovalRatesAreEstimates", { contentType: contentTypeLabel(t, quote.content_type) })}
      </p>
      <div className="flex justify-between">
        <Button variant="ghost" onClick={onBack}>
          {t("app.projects.new.wizard.back")}
        </Button>
        <Button variant="primary" onClick={onNext} disabled={!tier}>
          {t("app.projects.new.wizard.continue")}
        </Button>
      </div>
    </div>
  );
}
