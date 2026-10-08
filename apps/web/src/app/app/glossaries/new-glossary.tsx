"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { CONTENT_TYPES, contentTypeLabel } from "@/lib/langs";

export function NewGlossaryButton() {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [contentType, setContentType] = useState("");
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const g = await api.createGlossary({ name: name.trim(), content_type: contentType || undefined });
      toast.success(t("app.glossaries.newGlossary.glossaryCreated"));
      setOpen(false);
      router.push(`/app/glossaries/${g.id}`);
    } catch (err) {
      toast.error(t("app.glossaries.newGlossary.couldNotCreateGlossary"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Icons.plus className="size-4" /> {t("app.glossaries.newGlossary.newGlossary")}
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title={t("app.glossaries.newGlossary.newGlossary")} size="sm">
        <form id="new-glossary" onSubmit={create} className="space-y-4">
          <Field label={t("app.glossaries.newGlossary.name")}>{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} autoFocus />}</Field>
          <Field label={t("app.glossaries.newGlossary.contentType")} hint={t("app.glossaries.newGlossary.limitTheGlossaryToOne")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={contentType} onChange={(e) => setContentType(e.target.value)}>
                <option value="">{t("app.glossaries.newGlossary.allContent")}</option>
                {CONTENT_TYPES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {contentTypeLabel(t, c.value)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("app.glossaries.newGlossary.cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={busy} disabled={!name.trim()}>
              {t("app.glossaries.newGlossary.create")}
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
