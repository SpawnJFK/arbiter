"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
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
  { value: "projects:read", label: k("app.settings.apiKeys.apiKeys.readProjectsJobsAndSegments") },
  { value: "projects:write", label: k("app.settings.apiKeys.apiKeys.uploadFilesRequestQuotesCreate") },
  { value: "assets:read", label: k("app.settings.apiKeys.apiKeys.readGlossariesAndTm") },
  { value: "assets:write", label: k("app.settings.apiKeys.apiKeys.editGlossariesImportTm") },
  { value: "quality:read", label: k("app.settings.apiKeys.apiKeys.readQualityDashboard") },
];

export function ApiKeys({ initial }: { initial: ApiKey[] }) {
  const { t } = useI18n();
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
      toast.error(t("app.settings.apiKeys.apiKeys.couldNotCreateKey"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(k: ApiKey) {
    try {
      await api.deleteApiKey(k.id);
      setKeys((xs) => xs.filter((x) => x.id !== k.id));
      toast.success(t("app.settings.apiKeys.apiKeys.keyRevoked"));
      setDeleting(null);
    } catch (err) {
      toast.error(t("app.settings.apiKeys.apiKeys.couldNotRevokeKey"), errorMessage(err));
    }
  }

  const close = () => {
    setOpen(false);
    setCreated(null);
  };

  return (
    <Card>
      <CardHeader
        title={t("app.settings.apiKeys.apiKeys.apiKeys")}
        description={t("app.settings.apiKeys.apiKeys.useAsAuthorizationBearerAk")}
        actions={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Icons.plus className="size-4" /> {t("app.settings.apiKeys.apiKeys.newKey")}
          </Button>
        }
      />
      {keys.length === 0 ? (
        <EmptyState title={t("app.settings.apiKeys.apiKeys.noApiKeys")} description={t("app.settings.apiKeys.apiKeys.createAKeyToUpload")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("app.settings.apiKeys.apiKeys.name")}</Th>
              <Th>{t("app.settings.apiKeys.apiKeys.prefix")}</Th>
              <Th className="hidden md:table-cell">{t("app.settings.apiKeys.apiKeys.scopes")}</Th>
              <Th className="hidden sm:table-cell">{t("app.settings.apiKeys.apiKeys.created")}</Th>
              <Th className="hidden lg:table-cell">{t("app.settings.apiKeys.apiKeys.lastUsed")}</Th>
              <Th className="text-right">
                <span className="sr-only">{t("app.settings.apiKeys.apiKeys.actions")}</span>
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
                <Td className="hidden text-muted lg:table-cell">{k.last_used_at ? <Time iso={k.last_used_at} mode="relative" /> : t("app.settings.apiKeys.apiKeys.never")}</Td>
                <Td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => setDeleting(k)}>
                    {t("app.settings.apiKeys.apiKeys.revoke")}
                  </Button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}

      <Dialog open={open} onClose={close} title={created ? t("app.settings.apiKeys.apiKeys.copyYourNewKey") : t("app.settings.apiKeys.apiKeys.newApiKey")}>
        {created ? (
          <div className="space-y-4">
            <Callout tone="warn" title={t("app.settings.apiKeys.apiKeys.thisIsTheOnlyTime")}>
              {t("app.settings.apiKeys.apiKeys.storeItInYourSecret")}
            </Callout>
            <CopyField value={created.key} label={t("app.settings.apiKeys.apiKeys.apiKey")} />
            <div className="flex justify-end">
              <Button variant="primary" onClick={close}>
                {t("app.settings.apiKeys.apiKeys.iHaveStoredIt")}
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={create} className="space-y-4">
            <Field label={t("app.settings.apiKeys.apiKeys.name")} hint={t("app.settings.apiKeys.apiKeys.whereTheKeyIsUsed")}>
              {(id, d) => <Input id={id} aria-describedby={d} required value={name} onChange={(e) => setName(e.target.value)} />}
            </Field>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-[13px] font-medium">{t("app.settings.apiKeys.apiKeys.scopes")}</legend>
              {SCOPES.map((s) => (
                <Checkbox
                  key={s.value}
                  label={<span className="font-mono text-[12.5px]">{s.value}</span>}
                  hint={t(s.label)}
                  checked={scopes.includes(s.value)}
                  onChange={(e) => setScopes(e.target.checked ? [...scopes, s.value] : scopes.filter((x) => x !== s.value))}
                />
              ))}
            </fieldset>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close}>
                {t("app.settings.apiKeys.apiKeys.cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={!name.trim() || scopes.length === 0}>
                {t("app.settings.apiKeys.apiKeys.createKey")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        size="sm"
        title={t("app.settings.apiKeys.apiKeys.revokeThisKey")}
        description={t("app.settings.apiKeys.apiKeys.requestsUsingItFailImmediately")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              {t("app.settings.apiKeys.apiKeys.cancel")}
            </Button>
            <Button variant="danger" onClick={() => deleting && remove(deleting)}>
              {t("app.settings.apiKeys.apiKeys.revokeKey")}
            </Button>
          </>
        }
      />
    </Card>
  );
}
