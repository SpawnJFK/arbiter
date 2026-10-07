"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { CONTENT_TYPES } from "@/lib/langs";

export function NewGlossaryButton() {
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
      toast.success("Glossary created");
      setOpen(false);
      router.push(`/app/glossaries/${g.id}`);
    } catch (err) {
      toast.error("Could not create glossary", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Icons.plus className="size-4" /> New glossary
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="New glossary" size="sm">
        <form id="new-glossary" onSubmit={create} className="space-y-4">
          <Field label="Name">{(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} autoFocus />}</Field>
          <Field label="Content type" hint="Limit the glossary to one content type, or apply it to everything.">
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={contentType} onChange={(e) => setContentType(e.target.value)}>
                <option value="">All content</option>
                {CONTENT_TYPES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={busy} disabled={!name.trim()}>
              Create
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
