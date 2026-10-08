"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Icons } from "@/components/icons";
import { TermKindBadge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import { TERM_KINDS, type ImportResult, type ListResponse, type Term, type TermInput, type TermKind } from "@/lib/types";

const KIND_HELP: Record<TermKind, string> = {
  mandatory: k("app.glossaries.detail.termsManager.kindHelp.mandatory"),
  preferred: k("app.glossaries.detail.termsManager.kindHelp.preferred"),
  forbidden: k("app.glossaries.detail.termsManager.kindHelp.forbidden"),
  do_not_translate: k("app.glossaries.detail.termsManager.kindHelp.do_not_translate"),
};

export function TermsManager({ glossaryId, initial }: { glossaryId: string; initial: ListResponse<Term> }) {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [terms, setTerms] = useState(initial.items);
  const [q, setQ] = useState("");
  const [src, setSrc] = useState("");
  const [tgt, setTgt] = useState("");
  const [editing, setEditing] = useState<Term | "new" | null>(null);
  const [retiring, setRetiring] = useState<Term | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    try {
      const res = await api.terms(glossaryId, { q, source_lang: src, target_lang: tgt, limit: 200 });
      setTerms(res.items);
    } catch (err) {
      toast.error(t("app.glossaries.detail.termsManager.searchFailed"), errorMessage(err));
    }
  }

  async function retire(item: Term) {
    try {
      await api.retireTerm(item.id);
      setTerms((xs) => xs.filter((x) => x.id !== item.id));
      toast.success(t("app.glossaries.detail.termsManager.termRetired"), t("app.glossaries.detail.termsManager.keptInHistoryNewJobs"));
      setRetiring(null);
      router.refresh();
    } catch (err) {
      toast.error(t("app.glossaries.detail.termsManager.couldNotRetireTerm"), errorMessage(err));
    }
  }

  async function importFile(value: File) {
    setImporting(true);
    setImportResult(null);
    try {
      const r = await api.importGlossary(glossaryId, value);
      setImportResult(r);
      await search();
      router.refresh();
    } catch (err) {
      toast.error(t("app.glossaries.detail.termsManager.importFailed"), errorMessage(err));
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <form onSubmit={search} className="flex flex-1 flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1 sm:max-w-xs">
            <Icons.search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
            <Input aria-label={t("app.glossaries.detail.termsManager.searchTerms")} placeholder={t("app.glossaries.detail.termsManager.searchTerms")} value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
          </div>
          <LangSelect label={t("app.glossaries.detail.termsManager.sourceLanguage")} value={src} onChange={setSrc} />
          <LangSelect label={t("app.glossaries.detail.termsManager.targetLanguage")} value={tgt} onChange={setTgt} />
          <Button type="submit">{t("app.glossaries.detail.termsManager.search")}</Button>
        </form>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.tbx,.xml"
            className="sr-only"
            aria-label={t("app.glossaries.detail.termsManager.importCsvOrTbx")}
            onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])}
          />
          <Button onClick={() => fileRef.current?.click()} loading={importing}>
            <Icons.upload className="size-4" /> {t("app.glossaries.detail.termsManager.importCsvTbx")}
          </Button>
          <AnchorButton href={api.glossaryExportUrl(glossaryId, "csv")} download>
            {t("app.glossaries.detail.termsManager.exportCsv")}
          </AnchorButton>
          <AnchorButton href={api.glossaryExportUrl(glossaryId, "tbx")} download>
            {t("app.glossaries.detail.termsManager.exportTbx")}
          </AnchorButton>
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Icons.plus className="size-4" /> {t("app.glossaries.detail.termsManager.addTerm")}
          </Button>
        </div>
      </div>

      {importResult && (
        <Callout tone={importResult.errors?.length ? "warn" : "ok"} title={t("app.glossaries.detail.termsManager.importedTermsSkipped", { imported: importResult.imported, skipped: importResult.skipped })}>
          {importResult.errors && importResult.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-[13px]">
              {importResult.errors.slice(0, 10).map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </Callout>
      )}

      <Card>
        {terms.length === 0 ? (
          <EmptyState title={t("app.glossaries.detail.termsManager.noTerms")} description={t("app.glossaries.detail.termsManager.addTermsOneByOne")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.glossaries.detail.termsManager.sourceTerm")}</Th>
                <Th>{t("app.glossaries.detail.termsManager.targetTerm")}</Th>
                <Th>{t("app.glossaries.detail.termsManager.kind")}</Th>
                <Th className="hidden md:table-cell">{t("app.glossaries.detail.termsManager.pair")}</Th>
                <Th className="hidden lg:table-cell">{t("app.glossaries.detail.termsManager.note")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("app.glossaries.detail.termsManager.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {terms.map((term) => (
                <Tr key={term.id}>
                  <Td className="font-medium">
                    {term.source_term}
                    {term.case_sensitive && (
                      <span className="ml-1.5 text-[11px] font-normal text-faint" title={t("app.glossaries.detail.termsManager.caseSensitive")}>
                        {t("app.glossaries.detail.termsManager.aa")}
                      </span>
                    )}
                  </Td>
                  <Td>{term.target_term ?? <span className="text-faint">–</span>}</Td>
                  <Td>
                    <TermKindBadge kind={term.kind} />
                  </Td>
                  <Td className="hidden whitespace-nowrap font-mono text-[12.5px] text-muted md:table-cell">
                    {term.source_lang} → {term.target_lang}
                  </Td>
                  <Td className="hidden max-w-xs text-[13px] text-muted lg:table-cell">{term.note}</Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(term)} aria-label={t("app.glossaries.detail.termsManager.edit2", { source_term: term.source_term })}>
                        {t("app.glossaries.detail.termsManager.edit")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRetiring(term)} aria-label={t("app.glossaries.detail.termsManager.retire2", { source_term: term.source_term })}>
                        {t("app.glossaries.detail.termsManager.retire")}
                      </Button>
                    </div>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <TermDialog
        glossaryId={glossaryId}
        term={editing}
        onClose={() => setEditing(null)}
        onSaved={(term, isNew) => {
          setTerms((xs) => (isNew ? [term, ...xs] : xs.map((x) => (x.id === term.id ? term : x))));
          setEditing(null);
          router.refresh();
        }}
      />

      <Dialog
        open={retiring !== null}
        onClose={() => setRetiring(null)}
        size="sm"
        title={t("app.glossaries.detail.termsManager.retireThisTerm")}
        description={t("app.glossaries.detail.termsManager.retiringSetsAnEndDate")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRetiring(null)}>
              {t("app.glossaries.detail.termsManager.cancel")}
            </Button>
            <Button variant="danger" onClick={() => retiring && retire(retiring)}>
              {t("app.glossaries.detail.termsManager.retireTerm")}
            </Button>
          </>
        }
      >
        {retiring && (
          <p className="text-[13.5px]">
            <span className="font-medium">{retiring.source_term}</span> → {retiring.target_term ?? "–"}
          </p>
        )}
      </Dialog>
    </div>
  );
}

function LangSelect({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const { t } = useI18n();
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="w-36">
      <option value="">{label.startsWith("Source") ? t("app.glossaries.detail.termsManager.anySource") : t("app.glossaries.detail.termsManager.anyTarget")}</option>
      {LANGS.map((l) => (
        <option key={l} value={l}>
          {l}
        </option>
      ))}
    </Select>
  );
}

function TermDialog({
  glossaryId,
  term,
  onClose,
  onSaved,
}: {
  glossaryId: string;
  term: Term | "new" | null;
  onClose: () => void;
  onSaved: (item: Term, isNew: boolean) => void;
}) {
  const { t } = useI18n();
  const isNew = term === "new";
  const current = term && term !== "new" ? term : null;
  return (
    <Dialog open={term !== null} onClose={onClose} title={isNew ? t("app.glossaries.detail.termsManager.addTerm") : t("app.glossaries.detail.termsManager.editTerm")}>
      {term !== null && <TermForm key={current?.id ?? "new"} glossaryId={glossaryId} term={current} onCancel={onClose} onSaved={(x) => onSaved(x, isNew)} />}
    </Dialog>
  );
}

function TermForm({
  glossaryId,
  term,
  onCancel,
  onSaved,
}: {
  glossaryId: string;
  term: Term | null;
  onCancel: () => void;
  onSaved: (item: Term) => void;
}) {
  const { f, t } = useI18n();
  const toast = useToast();
  const [v, setV] = useState<TermInput>({
    source_lang: term?.source_lang ?? "en",
    target_lang: term?.target_lang ?? "de",
    source_term: term?.source_term ?? "",
    target_term: term?.target_term ?? "",
    kind: term?.kind ?? "mandatory",
    case_sensitive: term?.case_sensitive ?? false,
    note: term?.note ?? "",
  });
  const [busy, setBusy] = useState(false);
  const needsTarget = v.kind === "mandatory" || v.kind === "preferred";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const body: TermInput = {
      ...v,
      target_term: v.kind === "do_not_translate" ? undefined : v.target_term || undefined,
      note: v.note || undefined,
    };
    try {
      const saved = term ? await api.updateTerm(term.id, body) : await api.createTerm(glossaryId, body);
      toast.success(term ? t("app.glossaries.detail.termsManager.termUpdated") : t("app.glossaries.detail.termsManager.termAdded"), t("app.glossaries.detail.termsManager.glossaryVersionBumped"));
      onSaved(saved);
    } catch (err) {
      toast.error(t("app.glossaries.detail.termsManager.couldNotSaveTerm"), errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("app.glossaries.detail.termsManager.sourceLanguage")}>
          {(id) => (
            <Select id={id} value={v.source_lang} onChange={(e) => setV({ ...v, source_lang: e.target.value })}>
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {f.langName(l)} ({l})
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t("app.glossaries.detail.termsManager.targetLanguage")}>
          {(id) => (
            <Select id={id} value={v.target_lang} onChange={(e) => setV({ ...v, target_lang: e.target.value })}>
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {f.langName(l)} ({l})
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t("app.glossaries.detail.termsManager.sourceTerm")}>
          {(id) => <Input id={id} required value={v.source_term} onChange={(e) => setV({ ...v, source_term: e.target.value })} />}
        </Field>
        <Field label={v.kind === "forbidden" ? t("app.glossaries.detail.termsManager.forbiddenTargetTerm") : t("app.glossaries.detail.termsManager.targetTerm")} hint={v.kind === "do_not_translate" ? t("app.glossaries.detail.termsManager.notUsedTheSourceTerm") : undefined}>
          {(id, d) => (
            <Input
              id={id}
              aria-describedby={d}
              required={needsTarget}
              disabled={v.kind === "do_not_translate"}
              value={v.target_term ?? ""}
              onChange={(e) => setV({ ...v, target_term: e.target.value })}
            />
          )}
        </Field>
      </div>
      <fieldset>
        <legend className="mb-1.5 text-[13px] font-medium">{t("app.glossaries.detail.termsManager.kind")}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {TERM_KINDS.map((k) => (
            <label
              key={k}
              className={`flex cursor-pointer items-start gap-2 rounded-md border p-2.5 text-[13px] ${v.kind === k ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover"}`}
            >
              <input type="radio" name="kind" className="mt-0.5 accent-[var(--accent)]" checked={v.kind === k} onChange={() => setV({ ...v, kind: k })} />
              <span>
                <span className="font-medium">{t.enumLabel(k)}</span>
                <span className="block text-muted">{t(KIND_HELP[k])}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <Checkbox label={t("app.glossaries.detail.termsManager.caseSensitive")} checked={v.case_sensitive} onChange={(e) => setV({ ...v, case_sensitive: e.target.checked })} />
      <Field label={t("app.glossaries.detail.termsManager.noteForTranslatorsAndReviewers")}>
        {(id) => <Textarea id={id} value={v.note ?? ""} onChange={(e) => setV({ ...v, note: e.target.value })} className="min-h-16" />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          {t("app.glossaries.detail.termsManager.cancel")}
        </Button>
        <Button type="submit" variant="primary" loading={busy}>
          {term ? t("app.glossaries.detail.termsManager.saveChanges") : t("app.glossaries.detail.termsManager.addTerm")}
        </Button>
      </div>
    </form>
  );
}
