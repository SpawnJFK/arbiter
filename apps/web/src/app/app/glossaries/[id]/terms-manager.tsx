"use client";

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
import { humanize, langName } from "@/lib/format";
import { LANGS } from "@/lib/langs";
import { TERM_KINDS, type ImportResult, type ListResponse, type Term, type TermInput, type TermKind } from "@/lib/types";

const KIND_HELP: Record<TermKind, string> = {
  mandatory: "Target must use exactly this term.",
  preferred: "Use this term unless context requires otherwise.",
  forbidden: "This target term must never appear.",
  do_not_translate: "Keep the source term as is (names, product codes).",
};

export function TermsManager({ glossaryId, initial }: { glossaryId: string; initial: ListResponse<Term> }) {
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
      toast.error("Search failed", errorMessage(err));
    }
  }

  async function retire(t: Term) {
    try {
      await api.retireTerm(t.id);
      setTerms((xs) => xs.filter((x) => x.id !== t.id));
      toast.success("Term retired", "Kept in history; new jobs no longer use it.");
      setRetiring(null);
      router.refresh();
    } catch (err) {
      toast.error("Could not retire term", errorMessage(err));
    }
  }

  async function importFile(f: File) {
    setImporting(true);
    setImportResult(null);
    try {
      const r = await api.importGlossary(glossaryId, f);
      setImportResult(r);
      await search();
      router.refresh();
    } catch (err) {
      toast.error("Import failed", errorMessage(err));
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
            <Input aria-label="Search terms" placeholder="Search terms" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
          </div>
          <LangSelect label="Source language" value={src} onChange={setSrc} />
          <LangSelect label="Target language" value={tgt} onChange={setTgt} />
          <Button type="submit">Search</Button>
        </form>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.tbx,.xml"
            className="sr-only"
            aria-label="Import CSV or TBX"
            onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])}
          />
          <Button onClick={() => fileRef.current?.click()} loading={importing}>
            <Icons.upload className="size-4" /> Import CSV/TBX
          </Button>
          <AnchorButton href={api.glossaryExportUrl(glossaryId, "csv")} download>
            Export CSV
          </AnchorButton>
          <AnchorButton href={api.glossaryExportUrl(glossaryId, "tbx")} download>
            Export TBX
          </AnchorButton>
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Icons.plus className="size-4" /> Add term
          </Button>
        </div>
      </div>

      {importResult && (
        <Callout tone={importResult.errors?.length ? "warn" : "ok"} title={`Imported ${importResult.imported} terms, skipped ${importResult.skipped}`}>
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
          <EmptyState title="No terms" description="Add terms one by one or import a CSV/TBX file." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Source term</Th>
                <Th>Target term</Th>
                <Th>Kind</Th>
                <Th className="hidden md:table-cell">Pair</Th>
                <Th className="hidden lg:table-cell">Note</Th>
                <Th className="text-right">
                  <span className="sr-only">Actions</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {terms.map((t) => (
                <Tr key={t.id}>
                  <Td className="font-medium">
                    {t.source_term}
                    {t.case_sensitive && (
                      <span className="ml-1.5 text-[11px] font-normal text-faint" title="Case-sensitive">
                        Aa
                      </span>
                    )}
                  </Td>
                  <Td>{t.target_term ?? <span className="text-faint">–</span>}</Td>
                  <Td>
                    <TermKindBadge kind={t.kind} />
                  </Td>
                  <Td className="hidden whitespace-nowrap font-mono text-[12.5px] text-muted md:table-cell">
                    {t.source_lang} → {t.target_lang}
                  </Td>
                  <Td className="hidden max-w-xs text-[13px] text-muted lg:table-cell">{t.note}</Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(t)} aria-label={`Edit ${t.source_term}`}>
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRetiring(t)} aria-label={`Retire ${t.source_term}`}>
                        Retire
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
        onSaved={(t, isNew) => {
          setTerms((xs) => (isNew ? [t, ...xs] : xs.map((x) => (x.id === t.id ? t : x))));
          setEditing(null);
          router.refresh();
        }}
      />

      <Dialog
        open={retiring !== null}
        onClose={() => setRetiring(null)}
        size="sm"
        title="Retire this term?"
        description="Retiring sets an end date and bumps the glossary version. Jobs already running keep their frozen version."
        footer={
          <>
            <Button variant="ghost" onClick={() => setRetiring(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => retiring && retire(retiring)}>
              Retire term
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
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="w-36">
      <option value="">{label.startsWith("Source") ? "Any source" : "Any target"}</option>
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
  onSaved: (t: Term, isNew: boolean) => void;
}) {
  const isNew = term === "new";
  const t = term && term !== "new" ? term : null;
  return (
    <Dialog open={term !== null} onClose={onClose} title={isNew ? "Add term" : "Edit term"}>
      {term !== null && <TermForm key={t?.id ?? "new"} glossaryId={glossaryId} term={t} onCancel={onClose} onSaved={(x) => onSaved(x, isNew)} />}
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
  onSaved: (t: Term) => void;
}) {
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
      toast.success(term ? "Term updated" : "Term added", "Glossary version bumped.");
      onSaved(saved);
    } catch (err) {
      toast.error("Could not save term", errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Source language">
          {(id) => (
            <Select id={id} value={v.source_lang} onChange={(e) => setV({ ...v, source_lang: e.target.value })}>
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {langName(l)} ({l})
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Target language">
          {(id) => (
            <Select id={id} value={v.target_lang} onChange={(e) => setV({ ...v, target_lang: e.target.value })}>
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {langName(l)} ({l})
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Source term">
          {(id) => <Input id={id} required value={v.source_term} onChange={(e) => setV({ ...v, source_term: e.target.value })} />}
        </Field>
        <Field label={v.kind === "forbidden" ? "Forbidden target term" : "Target term"} hint={v.kind === "do_not_translate" ? "Not used: the source term is kept." : undefined}>
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
        <legend className="mb-1.5 text-[13px] font-medium">Kind</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {TERM_KINDS.map((k) => (
            <label
              key={k}
              className={`flex cursor-pointer items-start gap-2 rounded-md border p-2.5 text-[13px] ${v.kind === k ? "border-accent bg-accent-subtle/50" : "border-border hover:bg-hover"}`}
            >
              <input type="radio" name="kind" className="mt-0.5 accent-[var(--accent)]" checked={v.kind === k} onChange={() => setV({ ...v, kind: k })} />
              <span>
                <span className="font-medium">{humanize(k)}</span>
                <span className="block text-muted">{KIND_HELP[k]}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <Checkbox label="Case-sensitive" checked={v.case_sensitive} onChange={(e) => setV({ ...v, case_sensitive: e.target.checked })} />
      <Field label="Note for translators and reviewers">
        {(id) => <Textarea id={id} value={v.note ?? ""} onChange={(e) => setV({ ...v, note: e.target.value })} className="min-h-16" />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={busy}>
          {term ? "Save changes" : "Add term"}
        </Button>
      </div>
    </form>
  );
}
