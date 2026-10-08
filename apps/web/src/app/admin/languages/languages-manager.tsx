"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input } from "@/components/ui/input";
import { Callout, Progress } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { SOURCE_LOCALE } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import type { LocaleInfo } from "@/lib/i18n/locales";
import { EXPORT_FORMATS } from "@/lib/i18n/transfer";

export type LanguageRow = LocaleInfo & { translated: number };

type PlaceholderErrors = Record<string, { expected: string[]; got: string[] }>;
type ApiErr = { error?: { code?: string; message?: string; details?: Record<string, unknown> } };

async function call(url: string, init: RequestInit): Promise<{ ok: boolean; data: (ApiErr & Record<string, unknown>) | null }> {
  const res = await fetch(url, init);
  const data = res.status === 204 ? null : ((await res.json().catch(() => null)) as (ApiErr & Record<string, unknown>) | null);
  return { ok: res.ok, data };
}

export function LanguagesManager({ rows, total }: { rows: LanguageRow[]; total: number }) {
  const { t, f } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState<LanguageRow | null>(null);
  const [deleting, setDeleting] = useState<LanguageRow | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // Optimistic switch state until the refreshed rows arrive.
  const [optimistic, setOptimistic] = useState<Record<string, boolean>>({});

  async function toggle(row: LanguageRow, enabled: boolean) {
    setBusy(row.locale);
    setOptimistic((o) => ({ ...o, [row.locale]: enabled }));
    const { ok, data } = await call(`/api/i18n/locales/${encodeURIComponent(row.locale)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: row.name, enabled }),
    });
    setBusy(null);
    if (!ok) {
      setOptimistic((o) => {
        const { [row.locale]: _drop, ...rest } = o;
        void _drop;
        return rest;
      });
      return toast.error(t("admin.languages.updateFailed"), data?.error?.message);
    }
    toast.success(enabled ? t("admin.languages.enabledToast", { name: row.name }) : t("admin.languages.disabledToast", { name: row.name }));
    router.refresh();
  }

  async function remove(row: LanguageRow) {
    setBusy(row.locale);
    const { ok, data } = await call(`/api/i18n/locales/${encodeURIComponent(row.locale)}`, { method: "DELETE" });
    setBusy(null);
    setDeleting(null);
    setOptimistic((o) => {
      const { [row.locale]: _drop, ...rest } = o;
      void _drop;
      return rest;
    });
    if (!ok) return toast.error(t("admin.languages.deleteFailed"), data?.error?.message);
    toast.success(t("admin.languages.deletedToast", { name: row.name }));
    router.refresh();
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-[13px] text-muted">{t("admin.languages.workflowHint")}</p>
        <Button variant="primary" onClick={() => setAdding(true)}>
          <Icons.plus className="size-4" /> {t("admin.languages.addLanguage")}
        </Button>
      </div>
      <Card>
        <Table>
          <THead>
            <tr>
              <Th>{t("admin.languages.language")}</Th>
              <Th>{t("admin.languages.enabled")}</Th>
              <Th className="text-right">{t("admin.languages.messages")}</Th>
              <Th className="w-44">{t("admin.languages.coverage")}</Th>
              <Th className="hidden lg:table-cell">{t("admin.languages.lastUpdated")}</Th>
              <Th className="text-right">{t("admin.languages.actions")}</Th>
            </tr>
          </THead>
          <TBody>
            {rows.map((row) => {
              const isSource = row.locale === SOURCE_LOCALE;
              const enabled = optimistic[row.locale] ?? row.enabled;
              const coverage = total ? row.translated / total : 0;
              return (
                <Tr key={row.locale}>
                  <Td>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{row.name}</span>
                      {isSource && <Badge tone="accent">{t("admin.languages.source")}</Badge>}
                    </div>
                    <div className="font-mono text-[12px] text-faint">{row.locale}</div>
                  </Td>
                  <Td>
                    <label className="inline-flex items-center gap-2 text-[13px]">
                      <input
                        type="checkbox"
                        role="switch"
                        className="size-4 accent-[var(--accent)]"
                        checked={enabled}
                        disabled={isSource || busy === row.locale}
                        onChange={(e) => void toggle(row, e.target.checked)}
                        aria-label={t("admin.languages.enableLanguage", { name: row.name })}
                      />
                      <span className={enabled ? "text-fg" : "text-muted"}>{enabled ? t("admin.languages.on") : t("admin.languages.off")}</span>
                    </label>
                  </Td>
                  <Td className="tabular text-right">{f.num(row.message_count ?? 0)}</Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <Progress value={coverage} tone={coverage >= 0.999 ? "ok" : "accent"} className="w-24" />
                      <span className="tabular text-[12.5px] text-muted">{f.pct(coverage, coverage > 0 && coverage < 0.1 ? 1 : 0)}</span>
                    </div>
                    {!isSource && <div className="text-[12px] text-faint">{t("admin.languages.translatedOf", { translated: f.num(row.translated), total: f.num(total) })}</div>}
                  </Td>
                  <Td className="hidden text-[13px] text-muted lg:table-cell">{isSource ? t("admin.languages.inRepo") : <Time iso={row.updated_at} />}</Td>
                  <Td>
                    <div className="flex flex-wrap items-center justify-end gap-1">
                      <span className="mr-1 text-[12px] text-faint">{t("admin.languages.export")}</span>
                      {EXPORT_FORMATS.map((fmt) => (
                        <a
                          key={fmt}
                          href={`/api/i18n/export?locale=${encodeURIComponent(row.locale)}&format=${fmt}`}
                          download
                          className={buttonClass("ghost", "sm")}
                          aria-label={t("admin.languages.exportAs", { name: row.name, format: t(`admin.languages.format.${fmt}`) })}
                        >
                          {t(`admin.languages.format.${fmt}`)}
                        </a>
                      ))}
                      {!isSource && (
                        <>
                          <Button size="sm" onClick={() => setImporting(row)} aria-label={t("admin.languages.importInto", { name: row.name })}>
                            <Icons.upload className="size-3.5" /> {t("admin.languages.import")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setDeleting(row)} aria-label={t("admin.languages.deleteLanguage", { name: row.name })}>
                            <Icons.trash className="size-3.5" />
                          </Button>
                        </>
                      )}
                    </div>
                  </Td>
                </Tr>
              );
            })}
          </TBody>
        </Table>
      </Card>

      <AddLanguageDialog open={adding} onClose={() => setAdding(false)} existing={rows.map((r) => r.locale)} />
      <ImportDialog row={importing} onClose={() => setImporting(null)} />
      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title={t("admin.languages.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("admin.languages.deleteDescription", { count: deleting?.message_count ?? 0 })}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              {t("admin.languages.cancel")}
            </Button>
            <Button variant="danger" loading={busy === deleting?.locale} onClick={() => deleting && void remove(deleting)}>
              {t("admin.languages.delete")}
            </Button>
          </>
        }
      />
    </>
  );
}

function AddLanguageDialog({ open, onClose, existing }: { open: boolean; onClose: () => void; existing: string[] }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const c = code.trim();
    if (existing.some((x) => x.toLowerCase() === c.toLowerCase())) {
      setError(t("admin.languages.alreadyExists", { code: c }));
      return;
    }
    setBusy(true);
    setError(null);
    const { ok, data } = await call(`/api/i18n/locales/${encodeURIComponent(c)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), enabled }),
    });
    setBusy(false);
    if (!ok) {
      setError(data?.error?.message ?? t("admin.languages.updateFailed"));
      return;
    }
    toast.success(t("admin.languages.addedToast", { name: name.trim() }));
    setCode("");
    setName("");
    setEnabled(false);
    onClose();
    router.refresh();
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("admin.languages.addLanguage")} description={t("admin.languages.addDescription")} size="sm">
      <form onSubmit={submit} className="space-y-4">
        {error && <Callout tone="danger">{error}</Callout>}
        <Field label={t("admin.languages.code")} hint={t("admin.languages.codeHint")}>
          {(id, d) => <Input id={id} aria-describedby={d} required value={code} onChange={(e) => setCode(e.target.value)} placeholder="de" autoComplete="off" spellCheck={false} className="font-mono" />}
        </Field>
        <Field label={t("admin.languages.name")} hint={t("admin.languages.nameHint")}>
          {(id, d) => <Input id={id} aria-describedby={d} required value={name} onChange={(e) => setName(e.target.value)} placeholder="Deutsch" />}
        </Field>
        <Checkbox label={t("admin.languages.enableNow")} hint={t("admin.languages.enableNowHint")} checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            {t("admin.languages.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!code.trim() || !name.trim()}>
            {t("admin.languages.add")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ImportDialog({ row, onClose }: { row: LanguageRow | null; onClose: () => void }) {
  const { t, f } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placeholderErrors, setPlaceholderErrors] = useState<PlaceholderErrors | null>(null);

  function close() {
    setFile(null);
    setMode("merge");
    setError(null);
    setPlaceholderErrors(null);
    onClose();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!row || !file) return;
    setBusy(true);
    setError(null);
    setPlaceholderErrors(null);
    const form = new FormData();
    form.set("file", file);
    form.set("locale", row.locale);
    form.set("mode", mode);
    const { ok, data } = await call("/api/i18n/import", { method: "POST", body: form });
    setBusy(false);
    if (!ok) {
      const ph = data?.error?.details?.placeholders as PlaceholderErrors | undefined;
      setError(ph ? t("admin.languages.placeholderTitle") : data?.error?.message ?? t("admin.languages.importFailed"));
      if (ph) setPlaceholderErrors(ph);
      return;
    }
    const r = data as { upserted: number; deleted: number; total: number; unknown_count?: number; empty?: number };
    toast.success(
      t("admin.languages.importedToast", { name: row.name }),
      [
        t("admin.languages.importSummary", { upserted: f.num(r.upserted), deleted: f.num(r.deleted), total: f.num(r.total) }),
        r.unknown_count ? t("admin.languages.importUnknown", { count: r.unknown_count }) : null,
      ]
        .filter(Boolean)
        .join(" "),
    );
    close();
    router.refresh();
  }

  const entries = placeholderErrors ? Object.entries(placeholderErrors) : [];
  return (
    <Dialog open={row !== null} onClose={close} title={t("admin.languages.importTitle", { name: row?.name ?? "" })} description={t("admin.languages.importDescription")} size="md">
      <form onSubmit={submit} className="space-y-4">
        {error && (
          <Callout tone="danger" title={error}>
            {entries.length > 0 && (
              <>
                <p className="mb-2">{t("admin.languages.placeholderHelp", { count: entries.length })}</p>
                <ul className="max-h-60 space-y-1.5 overflow-y-auto font-mono text-[12px]" aria-label={t("admin.languages.placeholderErrors")}>
                  {entries.map(([key, v]) => (
                    <li key={key}>
                      <div className="font-medium text-fg">{key}</div>
                      <div className="text-muted">
                        {t("admin.languages.expectedGot", {
                          expected: v.expected.length ? v.expected.map((x) => `{${x}}`).join(" ") : t("admin.languages.none"),
                          got: v.got.length ? v.got.map((x) => `{${x}}`).join(" ") : t("admin.languages.none"),
                        })}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Callout>
        )}
        <Field label={t("admin.languages.file")} hint={t("admin.languages.fileHint")}>
          {(id, d) => (
            <input
              id={id}
              aria-describedby={d}
              type="file"
              required
              accept=".json,.csv,.xlf,.xliff,application/json,text/csv,application/xliff+xml"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-[13px] file:mr-3 file:rounded-md file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-[13px] file:font-medium"
            />
          )}
        </Field>
        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium">{t("admin.languages.mode")}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {(["merge", "replace"] as const).map((m) => (
              <label key={m} className={`flex cursor-pointer gap-2.5 rounded-md border p-3 text-[13px] ${mode === m ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover"}`}>
                <input type="radio" name="mode" className="mt-0.5 accent-[var(--accent)]" checked={mode === m} onChange={() => setMode(m)} />
                <span>
                  <span className="font-medium">{t(`admin.languages.mode.${m}.label`)}</span>
                  <span className="mt-0.5 block text-muted">{t(`admin.languages.mode.${m}.hint`)}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={close}>
            {t("admin.languages.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!file}>
            {t("admin.languages.import")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
