"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { LANGS } from "@/lib/langs";
import type { Alignment } from "@/lib/types-workbench";

export function TmAlign({ canEdit }: { canEdit: boolean }) {
  const { t } = useI18n();
  const toast = useToast();
  const [src, setSrc] = useState<File | null>(null);
  const [tgt, setTgt] = useState<File | null>(null);
  const [sl, setSl] = useState("en");
  const [tl, setTl] = useState("de");
  const [busy, setBusy] = useState(false);
  const [al, setAl] = useState<Alignment | null>(null);
  const [accepted, setAccepted] = useState<Record<number, boolean>>({});
  const [rights, setRights] = useState(false);
  const [result, setResult] = useState<{ imported: number; skipped: number } | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!src || !tgt) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await api.createAlignment(src, tgt, sl, tl);
      setAl(res);
      setAccepted(Object.fromEntries(res.pairs.map((p) => [p.index, p.accepted])));
    } catch (err) {
      toast.error(t("app.tm.align.failed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!al || !rights) return;
    setBusy(true);
    try {
      const res = await api.commitAlignment(
        al.id,
        al.pairs.map((p) => ({ index: p.index, accepted: !!accepted[p.index] })),
      );
      setResult({ imported: res.imported, skipped: res.skipped });
      setAl(res.alignment);
    } catch (err) {
      toast.error(t("app.tm.align.commitFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) return <Callout tone="info">{t("app.tm.align.pmOnly")}</Callout>;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("app.tm.align.title")} description={t("app.tm.align.description")} />
        <CardBody>
          <form onSubmit={run} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto_auto] sm:items-end">
            <Field label={t("app.tm.align.sourceFile")}>
              {(id) => <input id={id} type="file" onChange={(e) => setSrc(e.target.files?.[0] ?? null)} className="block w-full text-[13px]" />}
            </Field>
            <Field label={t("app.tm.align.targetFile")}>
              {(id) => <input id={id} type="file" onChange={(e) => setTgt(e.target.files?.[0] ?? null)} className="block w-full text-[13px]" />}
            </Field>
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
            <Button type="submit" variant="primary" loading={busy} disabled={!src || !tgt}>
              <Icons.upload className="size-4" /> {t("app.tm.align.align")}
            </Button>
          </form>
        </CardBody>
      </Card>

      {al && (
        <Card>
          <CardHeader
            title={t("app.tm.align.grid", { pairs: al.stats.pairs })}
            description={t("app.tm.align.stats", { low: al.stats.low_confidence, unaligned: al.stats.unaligned })}
          />
          <ul className="max-h-[60vh] divide-y divide-border overflow-y-auto">
            {al.pairs.map((p) => (
              <li key={p.index} className={cn("grid gap-3 px-4 py-2.5 text-[13.5px] sm:grid-cols-[auto_1fr_1fr_auto]", !accepted[p.index] && "opacity-60")}>
                <input
                  type="checkbox"
                  aria-label={t("app.tm.align.accept")}
                  checked={!!accepted[p.index]}
                  disabled={al.status === "committed" || !p.source || !p.target}
                  onChange={(e) => setAccepted((a) => ({ ...a, [p.index]: e.target.checked }))}
                  className="mt-1 size-4 accent-[var(--accent)]"
                />
                <span>{p.source || <span className="italic text-faint">{t("app.tm.align.nothing")}</span>}</span>
                <span>{p.target || <span className="italic text-faint">{t("app.tm.align.nothing")}</span>}</span>
                <Badge tone={p.confidence >= 0.7 ? "ok" : p.confidence >= 0.5 ? "info" : "warn"} className="tabular">
                  {Math.round(p.confidence * 100)}%
                </Badge>
              </li>
            ))}
          </ul>
          <div className="space-y-3 border-t border-border px-4 py-3">
            {al.status === "committed" ? (
              <Callout tone="ok" title={t("app.tm.align.committed")}>
                {result
                  ? t("app.tm.align.committedCount", { imported: result.imported, skipped: result.skipped })
                  : t("app.tm.align.committedCount", { imported: al.committed_count, skipped: 0 })}
              </Callout>
            ) : (
              <>
                <Checkbox checked={rights} onChange={(e) => setRights(e.target.checked)} label={t("app.tm.align.rights")} hint={t("app.tm.align.rightsHint")} />
                <Button variant="primary" loading={busy} disabled={!rights} onClick={() => void commit()}>
                  {t("app.tm.align.commit", { n: Object.values(accepted).filter(Boolean).length })}
                </Button>
              </>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
