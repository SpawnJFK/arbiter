"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Input, Select } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import type { ImportResult, TmHit } from "@/lib/types";

export function TmScreen() {
  const { t } = useI18n();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const [q, setQ] = useState("");
  const [src, setSrc] = useState("en");
  const [tgt, setTgt] = useState("de");
  const [hits, setHits] = useState<TmHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  async function doImport(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !rights) return;
    setImporting(true);
    setResult(null);
    try {
      setResult(await api.importTm(file));
      setFile(null);
      setRights(false);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      toast.error(t("app.tm.tmScreen.importFailed"), errorMessage(err));
    } finally {
      setImporting(false);
    }
  }

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setSearching(true);
    try {
      setHits((await api.tmSearch({ q, source_lang: src, target_lang: tgt, limit: 50 })).items);
    } catch (err) {
      toast.error(t("app.tm.tmScreen.searchFailed"), errorMessage(err));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.6fr]">
      <Card className="self-start">
        <CardHeader title={t("app.tm.tmScreen.importTmx")} description={t("app.tm.tmScreen.tmx14InlineTags")} />
        <CardBody>
          <form onSubmit={doImport} className="space-y-4">
            <div>
              <input
                ref={fileRef}
                id="tmx-file"
                type="file"
                accept=".tmx,.xml"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-[13px] text-muted file:mr-3 file:h-8 file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:text-[13px] file:font-medium file:text-fg hover:file:bg-hover"
                aria-label={t("app.tm.tmScreen.tmxFile")}
              />
            </div>
            <div className="rounded-md border border-border bg-subtle/50 p-3">
              <Checkbox
                checked={rights}
                onChange={(e) => setRights(e.target.checked)}
                label={t("app.tm.tmScreen.iConfirmWeOwnThe")}
                hint={t("app.tm.tmScreen.onlyImportTmsYourOrganisation")}
                required
              />
            </div>
            <Button type="submit" variant="primary" loading={importing} disabled={!file || !rights}>
              <Icons.upload className="size-4" /> {t("app.tm.tmScreen.import")}
            </Button>
            {result && (
              <Callout tone="ok" title={t("app.tm.tmScreen.importFinished")}>
                {t("app.tm.tmScreen.entriesImportedSkippedDuplicatesOr", { imported: result.imported, skipped: result.skipped })}
              </Callout>
            )}
          </form>
        </CardBody>
        <div className="border-t border-border px-4 py-3">
          <AnchorButton size="sm" href={api.tmExportUrl({ source_lang: src, target_lang: tgt })} download>
            <Icons.download className="size-3.5" /> {t("app.tm.tmScreen.exportAsTmx", { src: src, tgt: tgt })}
          </AnchorButton>
        </div>
      </Card>

      <Card>
        <CardHeader title={t("app.tm.tmScreen.search")} description={t("app.tm.tmScreen.exactFuzzyAndSemanticMatches")} />
        <form onSubmit={search} className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <div className="relative min-w-48 flex-1">
            <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
            <Input aria-label={t("app.tm.tmScreen.searchText")} className="pl-8" placeholder={t("app.tm.tmScreen.searchSourceOrTargetText")} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select aria-label={t("app.tm.tmScreen.sourceLanguage")} value={src} onChange={(e) => setSrc(e.target.value)} className="w-24">
            {LANGS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
          <Select aria-label={t("app.tm.tmScreen.targetLanguage")} value={tgt} onChange={(e) => setTgt(e.target.value)} className="w-24">
            {LANGS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
          <Button type="submit" loading={searching}>
            {t("app.tm.tmScreen.search")}
          </Button>
        </form>
        {hits === null ? (
          <EmptyState title={t("app.tm.tmScreen.searchYourMemory")} description={t("app.tm.tmScreen.typeAPhraseToSee")} />
        ) : hits.length === 0 ? (
          <EmptyState title={t("app.tm.tmScreen.noMatches")} description={t("app.tm.tmScreen.tryFewerWordsOrAnother")} />
        ) : (
          <ul className="divide-y divide-border">
            {hits.map((h) => (
              <li key={h.entry_id} className="grid gap-3 px-4 py-3 text-[13.5px] sm:grid-cols-[1fr_1fr_auto]">
                <TaggedText value={h.source_tagged} />
                <TaggedText value={h.target_tagged} />
                <div className="flex items-start gap-1.5 sm:flex-col sm:items-end">
                  <Badge tone={(h.score <= 1 ? h.score * 100 : h.score) >= 100 ? "ok" : (h.score <= 1 ? h.score * 100 : h.score) >= 75 ? "info" : "neutral"} className="tabular">
                    {Math.round(h.score <= 1 ? h.score * 100 : Math.min(h.score, 100))}%
                  </Badge>
                  <span className="text-[12px] text-faint">{h.kind}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
