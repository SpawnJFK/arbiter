"use client";

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
      toast.error("Import failed", errorMessage(err));
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
      toast.error("Search failed", errorMessage(err));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.6fr]">
      <Card className="self-start">
        <CardHeader title="Import TMX" description="TMX 1.4. Inline tags are converted to the Arbiter tag format." />
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
                aria-label="TMX file"
              />
            </div>
            <div className="rounded-md border border-border bg-subtle/50 p-3">
              <Checkbox
                checked={rights}
                onChange={(e) => setRights(e.target.checked)}
                label="I confirm we own the rights to this translation memory"
                hint="Only import TMs your organisation owns or is licensed to reuse. Imported entries can be matched in your jobs only."
                required
              />
            </div>
            <Button type="submit" variant="primary" loading={importing} disabled={!file || !rights}>
              <Icons.upload className="size-4" /> Import
            </Button>
            {result && (
              <Callout tone="ok" title="Import finished">
                {result.imported} entries imported, {result.skipped} skipped (duplicates or empty targets).
              </Callout>
            )}
          </form>
        </CardBody>
        <div className="border-t border-border px-4 py-3">
          <AnchorButton size="sm" href={api.tmExportUrl({ source_lang: src, target_lang: tgt })} download>
            <Icons.download className="size-3.5" /> Export {src} → {tgt} as TMX
          </AnchorButton>
        </div>
      </Card>

      <Card>
        <CardHeader title="Search" description="Exact, fuzzy and semantic matches, scored like the pipeline scores them." />
        <form onSubmit={search} className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <div className="relative min-w-48 flex-1">
            <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
            <Input aria-label="Search text" className="pl-8" placeholder="Search source or target text" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select aria-label="Source language" value={src} onChange={(e) => setSrc(e.target.value)} className="w-24">
            {LANGS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
          <Select aria-label="Target language" value={tgt} onChange={(e) => setTgt(e.target.value)} className="w-24">
            {LANGS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
          <Button type="submit" loading={searching}>
            Search
          </Button>
        </form>
        {hits === null ? (
          <EmptyState title="Search your memory" description="Type a phrase to see what the pipeline would reuse." />
        ) : hits.length === 0 ? (
          <EmptyState title="No matches" description="Try fewer words or another language pair." />
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
