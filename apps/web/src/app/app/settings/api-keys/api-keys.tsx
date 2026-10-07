"use client";

import { useState } from "react";
import { CopyField } from "@/components/copy-field";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";

// The contract leaves scopes open; these map to the API areas in docs/api-contract.md.
const SCOPES = [
  { value: "projects:read", label: "Read projects, jobs and segments" },
  { value: "projects:write", label: "Upload files, request quotes, create projects" },
  { value: "assets:read", label: "Read glossaries and TM" },
  { value: "assets:write", label: "Edit glossaries, import TM" },
  { value: "quality:read", label: "Read quality dashboard" },
];

export function ApiKeys({ initial }: { initial: ApiKey[] }) {
  const toast = useToast();
  const [keys, setKeys] = useState(initial);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["projects:read", "projects:write"]);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [deleting, setDeleting] = useState<ApiKey | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const k = await api.createApiKey({ name: name.trim(), scopes });
      setCreated(k);
      setKeys((xs) => [{ id: k.id, name: k.name, prefix: k.prefix, scopes, created_at: new Date().toISOString() }, ...xs]);
      setName("");
    } catch (err) {
      toast.error("Could not create key", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(k: ApiKey) {
    try {
      await api.deleteApiKey(k.id);
      setKeys((xs) => xs.filter((x) => x.id !== k.id));
      toast.success("Key revoked");
      setDeleting(null);
    } catch (err) {
      toast.error("Could not revoke key", errorMessage(err));
    }
  }

  const close = () => {
    setOpen(false);
    setCreated(null);
  };

  return (
    <Card>
      <CardHeader
        title="API keys"
        description="Use as Authorization: Bearer ak_<prefix>.<secret>. Keys act on behalf of your organisation."
        actions={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Icons.plus className="size-4" /> New key
          </Button>
        }
      />
      {keys.length === 0 ? (
        <EmptyState title="No API keys" description="Create a key to upload files and fetch results from your own pipeline." />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>Name</Th>
              <Th>Prefix</Th>
              <Th className="hidden md:table-cell">Scopes</Th>
              <Th className="hidden sm:table-cell">Created</Th>
              <Th className="hidden lg:table-cell">Last used</Th>
              <Th className="text-right">
                <span className="sr-only">Actions</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {keys.map((k) => (
              <Tr key={k.id}>
                <Td className="font-medium">{k.name}</Td>
                <Td className="font-mono text-[12.5px] text-muted">{k.prefix}…</Td>
                <Td className="hidden md:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {(k.scopes ?? []).map((s) => (
                      <Badge key={s}>{s}</Badge>
                    ))}
                  </div>
                </Td>
                <Td className="hidden text-muted sm:table-cell">
                  <Time iso={k.created_at} />
                </Td>
                <Td className="hidden text-muted lg:table-cell">{k.last_used_at ? <Time iso={k.last_used_at} mode="relative" /> : "Never"}</Td>
                <Td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => setDeleting(k)}>
                    Revoke
                  </Button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}

      <Dialog open={open} onClose={close} title={created ? "Copy your new key" : "New API key"}>
        {created ? (
          <div className="space-y-4">
            <Callout tone="warn" title="This is the only time the key is shown">
              Store it in your secret manager now. If you lose it, revoke it and create a new one.
            </Callout>
            <CopyField value={created.key} label="API key" />
            <div className="flex justify-end">
              <Button variant="primary" onClick={close}>
                I have stored it
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={create} className="space-y-4">
            <Field label="Name" hint="Where the key is used, e.g. CI pipeline.">
              {(id, d) => <Input id={id} aria-describedby={d} required value={name} onChange={(e) => setName(e.target.value)} />}
            </Field>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-[13px] font-medium">Scopes</legend>
              {SCOPES.map((s) => (
                <Checkbox
                  key={s.value}
                  label={<span className="font-mono text-[12.5px]">{s.value}</span>}
                  hint={s.label}
                  checked={scopes.includes(s.value)}
                  onChange={(e) => setScopes(e.target.checked ? [...scopes, s.value] : scopes.filter((x) => x !== s.value))}
                />
              ))}
            </fieldset>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={!name.trim() || scopes.length === 0}>
                Create key
              </Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        size="sm"
        title="Revoke this key?"
        description="Requests using it fail immediately. This cannot be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => deleting && remove(deleting)}>
              Revoke key
            </Button>
          </>
        }
      />
    </Card>
  );
}
