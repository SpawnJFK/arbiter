"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { CopyField } from "@/components/copy-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { CustomRole, SsoConfig } from "@/lib/platform-api";

function parseDomains(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((d) => d.trim().toLowerCase().replace(/^@/, "")).filter(Boolean))];
}

export function SsoSettings({ initial, roles }: { initial: SsoConfig; roles: CustomRole[] }) {
  const { t } = useI18n();
  const toast = useToast();
  const [cfg, setCfg] = useState(initial);
  const [form, setForm] = useState({
    issuer: initial.issuer,
    client_id: initial.client_id,
    client_secret: "",
    domains: initial.domains.map((d) => d.domain).join("\n"),
    default_role: initial.default_role_id ? `role:${initial.default_role_id}` : initial.default_role,
    enforce_sso: initial.enforce_sso,
    enabled: initial.configured ? initial.enabled : true,
  });
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const anyVerified = cfg.domains.some((d) => d.verified);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const custom = form.default_role.startsWith("role:") ? form.default_role.slice(5) : null;
      const out = await api.saveSso({
        issuer: form.issuer.trim(),
        client_id: form.client_id.trim(),
        client_secret: form.client_secret || null,
        allowed_domains: parseDomains(form.domains),
        default_role: custom ? (roles.find((r) => r.id === custom)?.base_role ?? "client") : (form.default_role as "pm" | "client"),
        default_role_id: custom,
        enforce_sso: form.enforce_sso,
        enabled: form.enabled,
      });
      setCfg(out);
      setForm((f) => ({ ...f, client_secret: "" }));
      toast.success(t("platform.sso.saved"));
    } catch (err) {
      toast.error(t("platform.sso.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function verify(domain: string) {
    setVerifying(domain);
    try {
      setCfg(await api.verifySsoDomain(domain));
      toast.success(t("platform.sso.domainVerified", { domain }));
    } catch (err) {
      toast.error(t("platform.sso.couldNotVerify"), errorMessage(err));
    } finally {
      setVerifying(null);
    }
  }

  async function remove() {
    try {
      await api.deleteSso();
      setCfg({ ...cfg, configured: false, enabled: false, enforce_sso: false, client_secret_set: false, domains: [] });
      setForm({ issuer: "", client_id: "", client_secret: "", domains: "", default_role: "client", enforce_sso: false, enabled: true });
      setRemoving(false);
      toast.success(t("platform.sso.removed"));
    } catch (err) {
      toast.error(t("platform.sso.couldNotRemove"), errorMessage(err));
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("platform.sso.title")}
          description={t("platform.sso.description")}
          actions={
            cfg.configured && (
              <Badge tone={cfg.enabled ? "ok" : "neutral"} dot>
                {cfg.enabled ? (cfg.enforce_sso ? t("platform.sso.statusEnforced") : t("platform.sso.statusOn")) : t("platform.sso.statusOff")}
              </Badge>
            )
          }
        />
        <CardBody>
          <form onSubmit={save} className="space-y-4">
            <div>
              <div className="mb-1 text-[13px] font-medium">{t("platform.sso.redirectUri")}</div>
              <CopyField value={cfg.redirect_uri} label={t("platform.sso.redirectUri")} />
              <p className="mt-1 text-[12.5px] text-muted">{t("platform.sso.redirectUriHint")}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label={t("platform.sso.issuer")} hint={t("platform.sso.issuerHint")} className="md:col-span-2">
                {(id, d) => (
                  <Input id={id} aria-describedby={d} type="url" required placeholder="https://login.example.com" value={form.issuer} onChange={(e) => setForm({ ...form, issuer: e.target.value })} />
                )}
              </Field>
              <Field label={t("platform.sso.clientId")}>
                {(id) => <Input id={id} required autoComplete="off" value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} />}
              </Field>
              <Field label={t("platform.sso.clientSecret")} hint={cfg.client_secret_set ? t("platform.sso.clientSecretKept") : t("platform.sso.clientSecretHint")}>
                {(id, d) => (
                  <Input
                    id={id}
                    aria-describedby={d}
                    type="password"
                    autoComplete="new-password"
                    required={!cfg.client_secret_set}
                    value={form.client_secret}
                    onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
                  />
                )}
              </Field>
              <Field label={t("platform.sso.domains")} hint={t("platform.sso.domainsHint")}>
                {(id, d) => (
                  <Textarea id={id} aria-describedby={d} className="min-h-16 font-mono text-[13px]" placeholder="example.com" value={form.domains} onChange={(e) => setForm({ ...form, domains: e.target.value })} />
                )}
              </Field>
              <Field label={t("platform.sso.defaultRole")} hint={t("platform.sso.defaultRoleHint")}>
                {(id, d) => (
                  <Select id={id} aria-describedby={d} value={form.default_role} onChange={(e) => setForm({ ...form, default_role: e.target.value })}>
                    <option value="client">{t("platform.team.roleClient")}</option>
                    <option value="pm">{t("platform.team.rolePm")}</option>
                    {roles.length > 0 && (
                      <optgroup label={t("platform.team.customRoles")}>
                        {roles.map((r) => (
                          <option key={r.id} value={`role:${r.id}`}>
                            {r.name}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </Select>
                )}
              </Field>
            </div>
            <div className="space-y-2.5">
              <Checkbox label={t("platform.sso.enabled")} checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              <Checkbox
                label={t("platform.sso.enforce")}
                hint={anyVerified ? t("platform.sso.enforceHint") : t("platform.sso.enforceNeedsDomain")}
                disabled={!anyVerified}
                checked={form.enforce_sso}
                onChange={(e) => setForm({ ...form, enforce_sso: e.target.checked })}
              />
            </div>
            {form.enforce_sso && <Callout tone="warn">{t("platform.sso.enforceWarning")}</Callout>}
            <div className="flex flex-wrap justify-end gap-2">
              {cfg.configured && (
                <Button variant="outline-danger" className="mr-auto" onClick={() => setRemoving(true)}>
                  {t("platform.sso.remove")}
                </Button>
              )}
              <Button type="submit" variant="primary" loading={busy}>
                {t("platform.sso.save")}
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("platform.sso.domainsTitle")} description={t("platform.sso.domainsDescription")} />
        {cfg.domains.length === 0 ? (
          <EmptyState title={t("platform.sso.noDomains")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("platform.sso.domain")}</Th>
                <Th>{t("platform.team.status")}</Th>
                <Th className="hidden md:table-cell">{t("platform.sso.txtRecord")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("platform.common.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {cfg.domains.map((d) => (
                <Tr key={d.domain}>
                  <Td className="font-mono text-[13px]">{d.domain}</Td>
                  <Td>
                    <Badge tone={d.verified ? "ok" : "warn"} dot>
                      {d.verified ? t("platform.sso.verified") : t("platform.sso.pending")}
                    </Badge>
                  </Td>
                  <Td className="hidden max-w-[360px] md:table-cell">
                    {!d.verified && <CopyField value={d.txt_record} label={t("platform.sso.txtRecordFor", { domain: d.domain })} />}
                  </Td>
                  <Td className="text-right">
                    {!d.verified && (
                      <Button size="sm" loading={verifying === d.domain} onClick={() => verify(d.domain)}>
                        {t("platform.sso.verify")}
                      </Button>
                    )}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Dialog
        open={removing}
        onClose={() => setRemoving(false)}
        size="sm"
        title={t("platform.sso.removeTitle")}
        description={t("platform.sso.removeBody")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(false)}>
              {t("platform.common.cancel")}
            </Button>
            <Button variant="danger" onClick={remove}>
              {t("platform.sso.remove")}
            </Button>
          </>
        }
      />
    </div>
  );
}
