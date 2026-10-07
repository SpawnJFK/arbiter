"use client";

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
import { dateTime, hours, langName, money, num, pct, TIER_BLURB, TIER_LABEL } from "@/lib/format";
import { CONTENT_TYPES, contentTypeLabel, LANGS } from "@/lib/langs";
import { TIERS, type Account, type Quote, type Tier, type UploadedFile, type Workflow } from "@/lib/types";
import { WorkflowPipeline } from "@/components/workflow-pipeline";

const STEPS = ["File", "Languages", "Quote", "Confirm"] as const;

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
      if (!file) throw new Error("Choose a file first.");
      const f = await api.uploadFile(file, sourceLang);
      setUploaded(f);
      if (!name) setName(file.name.replace(/\.[^.]+$/, ""));
      setTargets((t) => t.filter((x) => x !== sourceLang));
      setStep(1);
    });

  const doQuote = () =>
    run(async () => {
      if (!uploaded) return;
      if (targets.length === 0) throw new Error("Pick at least one target language.");
      const q = await api.createQuote({ file_id: uploaded.id, target_langs: targets, content_type: contentType, account_id: accountId || undefined });
      setQuote(q);
      const wanted = workflow?.tier ?? account?.default_tier ?? defaultTier;
      const preferred = q.tiers[wanted]?.available ? wanted : TIERS.find((t) => q.tiers[t]?.available) ?? null;
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
      toast.success("Project started", `${project.target_langs.length} job(s) queued.`);
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
              <Field label="Project name" hint="Defaults to the file name.">
                {(id, d) => <Input id={id} aria-describedby={d} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. IFU v4.3" />}
              </Field>
              {accounts.length > 0 && (
                <Field label="Account" hint={account ? accountHint(account, workflows) : "Optional. Sets workflow, tier and price list."}>
                  {(id, d) => (
                    <Select id={id} aria-describedby={d} value={accountId} onChange={(e) => chooseAccount(e.target.value)}>
                      <option value="">No account</option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              )}
              <Field label="Source language">
                {(id) => (
                  <Select id={id} value={sourceLang} onChange={(e) => setSourceLang(e.target.value)}>
                    {LANGS.map((l) => (
                      <option key={l} value={l}>
                        {langName(l)} ({l})
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
          </div>
          <div className="mt-5 flex justify-end">
            <Button variant="primary" onClick={doUpload} loading={busy} disabled={!file}>
              Upload and continue
            </Button>
          </div>
        </Card>
      )}

      {step === 1 && uploaded && (
        <Card className="p-5">
          <FileSummary f={uploaded} sourceLang={sourceLang} />
          <div className="mt-5 grid gap-5 md:grid-cols-[1.4fr_1fr]">
            <fieldset>
              <div className="mb-2 flex items-end justify-between gap-3">
                <legend className="text-[13px] font-medium">
                  Target languages <span className="font-normal text-muted">({targets.length} selected)</span>
                </legend>
                <Input
                  aria-label="Filter languages"
                  placeholder="Filter…"
                  value={langFilter}
                  onChange={(e) => setLangFilter(e.target.value)}
                  className="h-7 max-w-40 text-[13px]"
                />
              </div>
              <div className="grid max-h-64 grid-cols-2 gap-1 overflow-y-auto rounded-md border border-border p-1.5 sm:grid-cols-3">
                {LANGS.filter((l) => l !== sourceLang)
                  .filter((l) => !langFilter || `${l} ${langName(l)}`.toLowerCase().includes(langFilter.toLowerCase()))
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
                        <span className="truncate">{langName(l)}</span>
                        <span className="ml-auto font-mono text-[11px] text-faint">{l}</span>
                      </label>
                    );
                  })}
              </div>
            </fieldset>
            <div className="space-y-4">
              <Field label="Content type" hint="Sets the quality threshold and which reviewers qualify.">
                {(id, d) => (
                  <Select id={id} aria-describedby={d} value={contentType} onChange={(e) => setContentType(e.target.value)}>
                    {CONTENT_TYPES.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {regulated && (
                <Callout tone="info" title="Regulated organisation">
                  Your organisation is marked as regulated{vertical ? ` (${vertical.replace(/_/g, " ")})` : ""}. Only tiers with human
                  review will be offered.
                </Callout>
              )}
            </div>
          </div>
          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(0)}>
              Back
            </Button>
            <Button variant="primary" onClick={doQuote} loading={busy} disabled={targets.length === 0}>
              Get quote
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
          <h2 className="text-[15px] font-semibold">Confirm and start</h2>
          <dl className="mt-4 grid gap-x-8 gap-y-3 text-[13.5px] sm:grid-cols-2">
            <Row k="Project" v={name || uploaded.filename} />
            <Row k="File" v={`${uploaded.filename} · ${num(uploaded.word_count)} words`} />
            <Row k="Languages" v={`${quote.source_lang} → ${quote.target_langs.join(", ")}`} />
            <Row k="Content type" v={contentTypeLabel(quote.content_type)} />
            {account && <Row k="Account" v={account.name} />}
            <Row k="Workflow" v={workflow ? workflow.name : `${TIER_LABEL[tier]} (tier default)`} />
            <Row k="Tier" v={TIER_LABEL[tier]} />
            <Row k="Price" v={money(quote.tiers[tier].price, quote.currency)} />
            <Row k="Expected auto-approval" v={pct(quote.tiers[tier].est_auto_rate)} />
            <Row k="Estimated delivery" v={hours(quote.tiers[tier].eta_hours)} />
          </dl>
          <div className="mt-5 max-w-xs">
            <Field label="Due date (optional)" hint="We alert you if the estimate puts it at risk.">
              {(id, d) => <Input id={id} aria-describedby={d} type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />}
            </Field>
          </div>
          {(tier === "hybrid" || tier === "full") && (
            <Callout tone="info" className="mt-5">
              Segments that need a human go to vetted reviewers. If none is available, your organisation&apos;s reviewer policy
              applies; we never replace a paid human review with AI without telling you.
            </Callout>
          )}
          {regulated && (
            <Callout tone="warn" className="mt-3" title="Regulated content">
              Every shipped segment will carry a human or senate decision in the evidence pack. Machine-only tiers are not available
              for this organisation.
            </Callout>
          )}
          <div className="mt-5 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>
              Back
            </Button>
            <Button variant="primary" onClick={doCreate} loading={busy}>
              Start project · {money(quote.tiers[tier].price, quote.currency)}
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
  return (
    <ol className="flex items-center gap-2 overflow-x-auto text-[13px]" aria-label="Progress">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
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

function FileDrop({ file, onFile }: { file: File | null; onFile: (f: File) => void }) {
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
        const f = e.dataTransfer.files?.[0];
        if (f) onFile(f);
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
          <p className="text-[12.5px] text-muted">{(file.size / 1024).toFixed(0)} KB</p>
        </>
      ) : (
        <>
          <p className="mt-2 font-medium">Drop a file here</p>
          <p className="text-[12.5px] text-muted">DOCX, XLSX, PPTX, HTML, Markdown, JSON, PO, XLIFF</p>
        </>
      )}
      <label className="mt-3">
        <span className="sr-only">Choose file</span>
        <input
          ref={input}
          type="file"
          name="file"
          className="sr-only"
          accept=".docx,.xlsx,.pptx,.html,.htm,.md,.json,.po,.xlf,.xliff,.txt"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />
        <Button size="sm" onClick={() => input.current?.click()}>
          {file ? "Choose another file" : "Choose file"}
        </Button>
      </label>
    </div>
  );
}

function FileSummary({ f, sourceLang }: { f: UploadedFile; sourceLang: string }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13.5px]">
        <span className="font-medium">{f.filename}</span>
        <Badge>{f.format.toUpperCase()}</Badge>
        <span className="text-muted">{langName(sourceLang)}</span>
        <span className="tabular text-muted">{num(f.segment_count)} segments</span>
        <span className="tabular text-muted">{num(f.word_count)} words</span>
      </div>
      {f.warnings.length > 0 && (
        <Callout tone="warn" className="mt-3" title="File warnings">
          <ul className="list-disc pl-4">
            {f.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Callout>
      )}
    </div>
  );
}

function accountHint(a: Account, workflows: Workflow[]): string {
  const w = workflows.find((x) => x.id === a.workflow_template_id);
  const parts = [w ? `Workflow: ${w.name}` : a.default_tier ? `Tier: ${TIER_LABEL[a.default_tier]}` : "Org defaults", a.price_list_id ? "own price list" : null];
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
  onTier: (t: Tier) => void;
  onBack: () => void;
  onNext: () => void;
  workflows: Workflow[];
  workflowId: string;
  onWorkflow: (id: string) => void;
  accountName?: string;
}) {
  const workflow = workflows.find((w) => w.id === workflowId);
  const a = quote.analysis;
  const parts = useMemo(
    () => [
      { k: "Context match", v: a.tm_context, c: "bg-ok" },
      { k: "Exact match", v: a.tm_exact, c: "bg-ok/70" },
      { k: "Fuzzy match", v: a.tm_fuzzy, c: "bg-info" },
      { k: "Repetitions", v: a.repetitions, c: "bg-violet" },
      { k: "New", v: a.new, c: "bg-border-strong" },
    ],
    [a],
  );
  const total = parts.reduce((n, p) => n + p.v, 0) || 1;

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[15px] font-semibold">
            {num(quote.word_count)} words · {quote.source_lang} → {quote.target_langs.join(", ")}
          </h2>
          <span className="text-[12.5px] text-muted">Quote valid until {dateTime(quote.valid_until)}</span>
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
              {p.k} <span className="tabular font-medium text-fg">{num(p.v)}</span>
            </li>
          ))}
        </ul>
      </Card>

      {workflows.length > 0 && (
        <Card className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <label className="block min-w-64 flex-1 text-[13px] font-medium sm:max-w-sm">
              Workflow
              <Select className="mt-1" aria-label="Workflow" value={workflowId} onChange={(e) => onWorkflow(e.target.value)}>
                <option value="">None: use the tier you pick below</option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id} disabled={!quote.tiers[w.tier]?.available}>
                    {w.name} ({TIER_LABEL[w.tier]})
                  </option>
                ))}
              </Select>
            </label>
            {accountName && <p className="pb-2 text-[12.5px] text-muted">Prices from {accountName}&apos;s price list when it has one.</p>}
          </div>
          {workflow && (
            <>
              <WorkflowPipeline steps={workflow.steps} compact className="mt-3" />
              <p className="mt-2 text-[12.5px] text-muted">The workflow sets the tier to {TIER_LABEL[workflow.tier]}.</p>
            </>
          )}
        </Card>
      )}

      <div role="radiogroup" aria-label="Service tier" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {TIERS.map((t) => {
          const q = quote.tiers[t];
          if (!q) return null;
          const selected = tier === t;
          return (
            <label
              key={t}
              className={cn(
                "relative flex flex-col rounded-lg border bg-surface p-4 shadow-card transition-colors",
                q.available ? "cursor-pointer hover:border-faint" : "cursor-not-allowed bg-subtle/50",
                selected ? "border-accent ring-1 ring-accent" : "border-border",
              )}
            >
              <input
                type="radio"
                name="tier"
                value={t}
                className="sr-only"
                checked={selected}
                disabled={!q.available || (workflow !== undefined && workflow.tier !== t)}
                onChange={() => onTier(t)}
                aria-describedby={`tier-${t}-desc`}
              />
              <div className="flex items-center justify-between">
                <span className={cn("font-semibold", !q.available && "text-muted")}>{TIER_LABEL[t]}</span>
                {!q.available ? (
                  <Badge tone="warn">Not available</Badge>
                ) : selected ? (
                  <span className="flex size-4.5 items-center justify-center rounded-full bg-accent text-accent-fg">
                    <Icons.check className="size-3" />
                  </span>
                ) : (
                  <span className={cn("size-4.5 rounded-full border border-border-strong", !q.available && "opacity-40")} />
                )}
              </div>
              <div className={cn("tabular mt-3 text-2xl font-semibold tracking-tight", !q.available && "text-faint line-through decoration-1")}>
                {money(q.price, quote.currency)}
              </div>
              <dl className="mt-3 space-y-1.5 text-[13px]">
                <div className="flex justify-between">
                  <dt className="text-muted">Est. auto-approval</dt>
                  <dd className="tabular font-medium">{pct(q.est_auto_rate)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">Delivery estimate</dt>
                  <dd className="tabular font-medium">{hours(q.eta_hours)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">Human review</dt>
                  <dd className="font-medium">{t === "full" ? "Every segment" : t === "hybrid" ? "Below threshold" : "None"}</dd>
                </div>
              </dl>
              <p id={`tier-${t}-desc`} className="mt-3 border-t border-border pt-3 text-[12.5px] leading-relaxed text-muted">
                {q.available ? TIER_BLURB[t] : <span className="text-warn">{q.blocked_reason ?? "Not available for this project."}</span>}
              </p>
            </label>
          );
        })}
      </div>
      <p className="text-[12.5px] text-muted">
        Auto-approval rates are estimates from your TM coverage and the calibrated threshold for {contentTypeLabel(quote.content_type).toLowerCase()} content. Segments that do not clear the threshold go to the senate or a reviewer, as the tier defines.
      </p>
      <div className="flex justify-between">
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button variant="primary" onClick={onNext} disabled={!tier}>
          Continue
        </Button>
      </div>
    </div>
  );
}
