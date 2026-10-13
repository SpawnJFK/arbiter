"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage, type EngineScope } from "@/lib/api";
import type { EngineCatalogEntry, EngineCredential } from "@/lib/types";

const BOOLEAN_FIELDS = new Set(["json_mode"]);

function regionTone(region: string): "ok" | "neutral" {
  return region === "eu" ? "ok" : "neutral";
}

/** Catalog of providers plus the keys stored for this scope (org BYOK or platform). */
export function EngineKeys({
  scope,
  catalog,
  initial,
}: {
  scope: EngineScope;
  catalog: EngineCatalogEntry[];
  initial: EngineCredential[];
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [keys, setKeys] = useState(initial);
  const [adding, setAdding] = useState<EngineCatalogEntry | null>(null);
  const [deleting, setDeleting] = useState<EngineCredential | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  async function test(c: EngineCredential) {
    setTesting(c.id);
    try {
      const r = await api.testEngineCredential(c.id, scope);
      setKeys((xs) => xs.map((x) => (x.id === c.id ? r.credential : x)));
      if (r.ok) toast.success(t("engines.keys.testPassed"), r.detail);
      else toast.error(t("engines.keys.testFailed"), r.error ?? "");
    } catch (err) {
      toast.error(t("engines.keys.testFailed"), errorMessage(err));
    } finally {
      setTesting(null);
    }
  }

  async function toggle(c: EngineCredential) {
    try {
      const r = await api.updateEngineCredential(c.id, { enabled: !c.enabled }, scope);
      setKeys((xs) => xs.map((x) => (x.id === c.id ? r : x)));
    } catch (err) {
      toast.error(t("engines.keys.couldNotSave"), errorMessage(err));
    }
  }

  async function remove(c: EngineCredential) {
    try {
      await api.deleteEngineCredential(c.id, scope);
      setKeys((xs) => xs.filter((x) => x.id !== c.id));
      setDeleting(null);
      toast.success(t("engines.keys.keyDeleted"));
    } catch (err) {
      toast.error(t("engines.keys.couldNotSave"), errorMessage(err));
    }
  }

  const providerName = (p: string) => catalog.find((c) => c.provider === p)?.name ?? p;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("engines.catalog.title")} description={t("engines.catalog.description")} />
        <Table>
          <THead>
            <tr>
              <Th>{t("engines.catalog.provider")}</Th>
              <Th className="hidden md:table-cell">{t("engines.catalog.capabilities")}</Th>
              <Th className="hidden md:table-cell">{t("engines.catalog.regions")}</Th>
              <Th className="hidden lg:table-cell">{t("engines.catalog.price")}</Th>
              <Th>{t("engines.catalog.keySource")}</Th>
              <Th className="text-right">
                <span className="sr-only">{t("engines.catalog.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {catalog.map((c) => (
              <Tr key={c.provider}>
                <Td>
                  <div className="font-medium">{c.name}</div>
                  <div className="font-mono text-[11.5px] text-faint">{c.provider}</div>
                </Td>
                <Td className="hidden md:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {c.capabilities.map((cap) => (
                      <Badge key={cap}>{t(`engines.capability.${cap}`)}</Badge>
                    ))}
                    {c.glossary && <Badge tone="info">{t("engines.catalog.glossary")}</Badge>}
                  </div>
                </Td>
                <Td className="hidden md:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {c.regions.map((r) => (
                      <Badge key={r} tone={regionTone(r)}>
                        {t(`engines.region.${r}`)}
                      </Badge>
                    ))}
                  </div>
                </Td>
                <Td className="hidden font-mono text-[12.5px] text-muted lg:table-cell">
                  {c.price.output
                    ? t("engines.catalog.priceInOut", { input: c.price.input, output: c.price.output, unit: c.price.unit })
                    : t("engines.catalog.priceFlat", { input: c.price.input, unit: c.price.unit })}
                </Td>
                <Td>
                  <Badge tone={c.configured === "none" ? "neutral" : c.configured === "org" ? "accent" : "ok"}>
                    {t(`engines.source.${c.configured}`)}
                  </Badge>
                </Td>
                <Td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => setAdding(c)}>
                    <Icons.plus className="size-3.5" /> {t("engines.catalog.addKey")}
                  </Button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </Card>

      <Card>
        <CardHeader
          title={scope === "platform" ? t("engines.keys.platformTitle") : t("engines.keys.title")}
          description={scope === "platform" ? t("engines.keys.platformDescription") : t("engines.keys.description")}
        />
        {keys.length === 0 ? (
          <EmptyState title={t("engines.keys.empty")} description={t("engines.keys.emptyDescription")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("engines.keys.label")}</Th>
                <Th>{t("engines.keys.key")}</Th>
                <Th className="hidden md:table-cell">{t("engines.keys.engine")}</Th>
                <Th className="hidden lg:table-cell">{t("engines.keys.lastTest")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("engines.catalog.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {keys.map((c) => (
                <Tr key={c.id}>
                  <Td>
                    <div className="font-medium">{c.label}</div>
                    <div className="text-[12px] text-muted">{providerName(c.provider)}</div>
                  </Td>
                  <Td className="font-mono text-[12.5px] text-muted">{c.secret_hint || t("engines.keys.noSecret")}</Td>
                  <Td className="hidden md:table-cell">
                    <span className="font-mono text-[12px]">{c.engine}</span>
                    {typeof c.config.region === "string" && (
                      <Badge className="ml-1.5" tone={regionTone(c.config.region)}>
                        {t(`engines.region.${c.config.region}`)}
                      </Badge>
                    )}
                    {!c.enabled && (
                      <Badge className="ml-1.5" tone="warn">
                        {t("engines.keys.disabled")}
                      </Badge>
                    )}
                  </Td>
                  <Td className="hidden text-[13px] lg:table-cell">
                    {c.last_tested_at ? (
                      <span className={c.last_test_ok ? "text-ok" : "text-danger"} title={c.last_test_error ?? undefined}>
                        {c.last_test_ok ? t("engines.keys.ok") : t("engines.keys.failed")} · <Time iso={c.last_tested_at} mode="relative" />
                      </span>
                    ) : (
                      <span className="text-muted">{t("engines.keys.never")}</span>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap text-right">
                    <Button size="sm" variant="ghost" loading={testing === c.id} onClick={() => test(c)}>
                      {t("engines.keys.test")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => toggle(c)}>
                      {c.enabled ? t("engines.keys.disable") : t("engines.keys.enable")}
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={t("engines.keys.delete")} onClick={() => setDeleting(c)}>
                      <Icons.trash className="size-3.5" />
                    </Button>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {adding && (
        <AddKeyDialog
          scope={scope}
          entry={adding}
          onClose={() => setAdding(null)}
          onCreated={(c) => {
            setKeys((xs) => [...xs, c]);
            setAdding(null);
          }}
        />
      )}

      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        size="sm"
        title={t("engines.keys.deleteTitle")}
        description={t("engines.keys.deleteDescription")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              {t("engines.cancel")}
            </Button>
            <Button variant="danger" onClick={() => deleting && remove(deleting)}>
              {t("engines.keys.delete")}
            </Button>
          </>
        }
      />
    </div>
  );
}

function AddKeyDialog({
  scope,
  entry,
  onClose,
  onCreated,
}: {
  scope: EngineScope;
  entry: EngineCatalogEntry;
  onClose: () => void;
  onCreated: (c: EngineCredential) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [label, setLabel] = useState(entry.name);
  const [secret, setSecret] = useState<Record<string, string>>({});
  const [config, setConfig] = useState<Record<string, string | boolean>>(
    entry.models[0] && entry.config_fields.includes("model") ? { model: entry.models[0] } : {},
  );
  const [busy, setBusy] = useState(false);
  const [testAfter, setTestAfter] = useState(true);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      let created = await api.createEngineCredential({ provider: entry.provider, label, secret, config }, scope);
      if (testAfter) {
        const r = await api.testEngineCredential(created.id, scope);
        created = r.credential;
        if (r.ok) toast.success(t("engines.keys.savedAndTested"), r.detail);
        else toast.error(t("engines.keys.savedTestFailed"), r.error ?? "");
      } else {
        toast.success(t("engines.keys.saved"));
      }
      onCreated(created);
    } catch (err) {
      toast.error(t("engines.keys.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onClose={onClose} title={t("engines.keys.addTitle", { provider: entry.name })} description={t("engines.keys.addDescription")}>
      <form onSubmit={save} className="space-y-4">
        <Field label={t("engines.keys.label")}>{(id) => <Input id={id} value={label} onChange={(e) => setLabel(e.target.value)} />}</Field>
        {entry.secret_fields.map((f) => (
          <Field key={f} label={t(`engines.field.${f}`)}>
            {(id) =>
              f === "service_account_json" ? (
                <Textarea
                  id={id}
                  className="font-mono text-[12px]"
                  autoComplete="off"
                  spellCheck={false}
                  value={secret[f] ?? ""}
                  onChange={(e) => setSecret({ ...secret, [f]: e.target.value })}
                />
              ) : (
                <Input
                  id={id}
                  type="password"
                  autoComplete="off"
                  value={secret[f] ?? ""}
                  onChange={(e) => setSecret({ ...secret, [f]: e.target.value })}
                />
              )
            }
          </Field>
        ))}
        {entry.config_fields.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {entry.config_fields.map((f) =>
              BOOLEAN_FIELDS.has(f) ? (
                <Checkbox
                  key={f}
                  className="sm:col-span-2"
                  label={t(`engines.field.${f}`)}
                  checked={config[f] !== false}
                  onChange={(e) => setConfig({ ...config, [f]: e.target.checked })}
                />
              ) : f === "region" ? (
                <Field key={f} label={t(`engines.field.${f}`)} hint={t("engines.keys.regionHint")}>
                  {(id) => (
                    <Select id={id} value={String(config[f] ?? "global")} onChange={(e) => setConfig({ ...config, [f]: e.target.value })}>
                      {entry.regions.map((r) => (
                        <option key={r} value={r}>
                          {t(`engines.region.${r}`)}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              ) : (
                <Field key={f} label={t(`engines.field.${f}`)}>
                  {(id) => (
                    <>
                      <Input
                        id={id}
                        list={f === "model" && entry.models.length ? `${id}-models` : undefined}
                        value={String(config[f] ?? "")}
                        onChange={(e) => setConfig({ ...config, [f]: e.target.value })}
                      />
                      {f === "model" && entry.models.length > 0 && (
                        <datalist id={`${id}-models`}>
                          {entry.models.map((m) => (
                            <option key={m} value={m} />
                          ))}
                        </datalist>
                      )}
                    </>
                  )}
                </Field>
              ),
            )}
          </div>
        )}
        <Callout tone="info">{t("engines.keys.storedEncrypted")}</Callout>
        <Checkbox label={t("engines.keys.testAfterSave")} checked={testAfter} onChange={(e) => setTestAfter(e.target.checked)} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("engines.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            {t("engines.keys.saveKey")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
