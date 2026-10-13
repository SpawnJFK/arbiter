"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import type { TermExtraction } from "@/lib/types-workbench";

type Row = { pick: boolean; target: string; kind: string };

export function TermExtract({ glossaryId }: { glossaryId: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [mode, setMode] = useState<"job" | "file">("file");
  const [jobId, setJobId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sl, setSl] = useState("en");
  const [tl, setTl] = useState("de");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<TermExtraction | null>(null);
  const [rows, setRows] = useState<Record<string, Row>>({});

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const out = await api.extractTerms(
        glossaryId,
        mode === "job" ? { jobId: jobId.trim() } : { file: file ?? undefined, sourceLang: sl, targetLang: tl },
      );
      setRes(out);
      setRows(
        Object.fromEntries(
          out.items.map((c) => [c.source_term, { pick: false, target: c.target_candidates[0]?.term ?? "", kind: "preferred" }]),
        ),
      );
    } catch (err) {
      toast.error(t("app.glossaries.extract.failed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function accept() {
    if (!res) return;
    const terms = Object.entries(rows)
      .filter(([, r]) => r.pick)
      .map(([source, r]) => ({
        source_term: source,
        target_term: r.target.trim() || null,
        kind: r.kind,
        source_lang: res.source_lang,
        target_lang: res.target_lang || tl,
      }));
    if (terms.length === 0) return;
    setBusy(true);
    try {
      const out = await api.acceptTerms(glossaryId, terms);
      toast.success(t("app.glossaries.extract.added", { n: out.items.length }));
      setRes({ ...res, items: res.items.filter((c) => !rows[c.source_term]?.pick) });
      router.refresh();
    } catch (err) {
      toast.error(t("app.glossaries.extract.acceptFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const set = (term: string, patch: Partial<Row>) => setRows((r) => ({ ...r, [term]: { ...r[term], ...patch } }));
  const picked = Object.values(rows).filter((r) => r.pick).length;

  return (
    <Card className="mt-4">
      <CardHeader title={t("app.glossaries.extract.title")} description={t("app.glossaries.extract.description")} />
      <CardBody className="space-y-4">
        <form onSubmit={run} className="flex flex-wrap items-end gap-2">
          <Select aria-label={t("app.glossaries.extract.from")} className="w-40" value={mode} onChange={(e) => setMode(e.target.value as "job" | "file")}>
            <option value="file">{t("app.glossaries.extract.fromFile")}</option>
            <option value="job">{t("app.glossaries.extract.fromJob")}</option>
          </Select>
          {mode === "job" ? (
            <Input aria-label={t("app.glossaries.extract.jobId")} placeholder={t("app.glossaries.extract.jobId")} className="w-72" value={jobId} onChange={(e) => setJobId(e.target.value)} />
          ) : (
            <>
              <input type="file" aria-label={t("app.glossaries.extract.file")} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-[13px]" />
              <Select aria-label={t("app.tm.tmScreen.sourceLanguage")} className="w-24" value={sl} onChange={(e) => setSl(e.target.value)}>
                {LANGS.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </Select>
              <Select aria-label={t("app.tm.tmScreen.targetLanguage")} className="w-24" value={tl} onChange={(e) => setTl(e.target.value)}>
                {LANGS.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </Select>
            </>
          )}
          <Button type="submit" variant="primary" loading={busy} disabled={mode === "job" ? !jobId.trim() : !file}>
            <Icons.sparkle className="size-4" /> {t("app.glossaries.extract.run")}
          </Button>
        </form>
        {res &&
          (res.items.length === 0 ? (
            <EmptyState title={t("app.glossaries.extract.none")} />
          ) : (
            <>
              <ul className="divide-y divide-border rounded-md border border-border">
                {res.items.map((c) => {
                  const r = rows[c.source_term];
                  return (
                    <li key={c.source_term} className="grid items-center gap-3 px-3 py-2 text-[13.5px] sm:grid-cols-[auto_1fr_1fr_auto]">
                      <input
                        type="checkbox"
                        aria-label={t("app.glossaries.extract.pick")}
                        checked={!!r?.pick}
                        onChange={(e) => set(c.source_term, { pick: e.target.checked })}
                        className="size-4 accent-[var(--accent)]"
                      />
                      <div>
                        <span className="font-medium">{c.source_term}</span>{" "}
                        <Badge tone="neutral" className="tabular">
                          {c.frequency}x
                        </Badge>
                        {c.variants.length > 1 && <div className="text-[12px] text-faint">{c.variants.join(", ")}</div>}
                      </div>
                      <Field label={t("app.glossaries.extract.target")} className="[&>label]:sr-only">
                        {(id) => (
                          <Input
                            id={id}
                            list={`cand-${c.source_term}`}
                            value={r?.target ?? ""}
                            onChange={(e) => set(c.source_term, { target: e.target.value })}
                          />
                        )}
                      </Field>
                      <datalist id={`cand-${c.source_term}`}>
                        {c.target_candidates.map((x) => (
                          <option key={x.term} value={x.term} />
                        ))}
                      </datalist>
                      <Select aria-label={t("app.glossaries.extract.kind")} className="w-36" value={r?.kind ?? "preferred"} onChange={(e) => set(c.source_term, { kind: e.target.value })}>
                        <option value="preferred">{t.enumLabel("preferred")}</option>
                        <option value="mandatory">{t.enumLabel("mandatory")}</option>
                        <option value="do_not_translate">{t.enumLabel("do_not_translate")}</option>
                        <option value="forbidden">{t.enumLabel("forbidden")}</option>
                      </Select>
                    </li>
                  );
                })}
              </ul>
              <Button variant="primary" loading={busy} disabled={picked === 0} onClick={() => void accept()}>
                {t("app.glossaries.extract.accept", { n: picked })}
              </Button>
            </>
          ))}
      </CardBody>
    </Card>
  );
}
