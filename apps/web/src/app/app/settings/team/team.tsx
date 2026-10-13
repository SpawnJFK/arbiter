"use client";

import { useI18n } from "@/lib/i18n/client";
import { useMemo, useState } from "react";
import { CopyField } from "@/components/copy-field";
import { Icons } from "@/components/icons";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { CustomRole, InviteResult, Member, MemberStatus, RoleInput } from "@/lib/platform-api";

const STATUS_TONE: Record<MemberStatus, Tone> = { active: "ok", invited: "info", deactivated: "neutral" };

/** "client" | "pm" | "role:<id>" as one select value. */
function roleValue(m: Pick<Member, "role" | "role_id">): string {
  return m.role_id ? `role:${m.role_id}` : m.role;
}

function roleBody(value: string): { role?: "pm" | "client"; role_id?: string | null } {
  return value.startsWith("role:") ? { role_id: value.slice(5) } : { role: value as "pm" | "client", role_id: null };
}

export function Team({
  initialMembers,
  initialRoles,
  catalog,
  meId,
  canManageUsers,
  canManageRoles,
}: {
  initialMembers: Member[];
  initialRoles: CustomRole[];
  catalog: { key: string; description: string }[];
  meId: string;
  canManageUsers: boolean;
  canManageRoles: boolean;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [members, setMembers] = useState(initialMembers);
  const [roles, setRoles] = useState(initialRoles);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState({ email: "", name: "", role: "client" });
  const [invited, setInvited] = useState<InviteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<CustomRole | "new" | null>(null);
  const [deactivating, setDeactivating] = useState<Member | null>(null);

  const permLabel = (key: string, fallback?: string) => {
    const k = `platform.perm.${key.replace(".", "_")}`;
    return t.has(k) ? t(k) : (fallback ?? key);
  };
  const roleName = (m: Member) => m.role_name ?? t(m.role === "pm" ? "platform.team.rolePm" : "platform.team.roleClient");

  const roleOptions = (
    <>
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
    </>
  );

  async function sendInvite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const rb = roleBody(invite.role);
      const out = await api.inviteMember({
        email: invite.email.trim(),
        name: invite.name.trim(),
        ...(rb.role_id ? { role_id: rb.role_id } : { role: rb.role }),
      });
      setMembers((xs) => [...xs, out.user]);
      setInvited(out);
      setInvite({ email: "", name: "", role: invite.role });
      toast.success(t("platform.team.inviteSent"));
    } catch (err) {
      toast.error(t("platform.team.couldNotInvite"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(m: Member, value: string) {
    try {
      const out = await api.updateMember(m.id, roleBody(value));
      setMembers((xs) => xs.map((x) => (x.id === m.id ? out : x)));
      toast.success(t("platform.team.roleChanged"));
    } catch (err) {
      toast.error(t("platform.team.couldNotChangeRole"), errorMessage(err));
    }
  }

  async function setActive(m: Member, active: boolean) {
    try {
      const out = active ? await api.updateMember(m.id, { is_active: true }) : (await api.deactivateMember(m.id), { ...m, status: "deactivated" as const });
      setMembers((xs) => xs.map((x) => (x.id === m.id ? out : x)));
      setDeactivating(null);
      toast.success(active ? t("platform.team.reactivated") : t("platform.team.deactivated"));
    } catch (err) {
      toast.error(t("platform.team.couldNotUpdate"), errorMessage(err));
    }
  }

  async function removeRole(r: CustomRole) {
    try {
      await api.deleteRole(r.id);
      setRoles((xs) => xs.filter((x) => x.id !== r.id));
      setEditing(null);
      toast.success(t("platform.roles.deleted"));
    } catch (err) {
      toast.error(t("platform.roles.couldNotDelete"), errorMessage(err));
    }
  }

  const closeInvite = () => {
    setInviteOpen(false);
    setInvited(null);
  };

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("platform.team.members")}
          description={t("platform.team.membersDescription")}
          actions={
            canManageUsers && (
              <Button variant="primary" onClick={() => setInviteOpen(true)}>
                <Icons.plus className="size-4" /> {t("platform.team.invite")}
              </Button>
            )
          }
        />
        {members.length === 0 ? (
          <EmptyState title={t("platform.team.noMembers")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("platform.team.member")}</Th>
                <Th>{t("platform.team.role")}</Th>
                <Th className="hidden sm:table-cell">{t("platform.team.status")}</Th>
                <Th className="hidden md:table-cell">{t("platform.team.added")}</Th>
                {canManageUsers && (
                  <Th className="text-right">
                    <span className="sr-only">{t("platform.common.actions")}</span>
                  </Th>
                )}
              </tr>
            </THead>
            <TBody>
              {members.map((m) => {
                const self = m.id === meId;
                return (
                  <Tr key={m.id}>
                    <Td className="max-w-[130px] sm:max-w-[220px]">
                      <div className="truncate font-medium">
                        {m.name || m.email}
                        {self && <span className="ml-1.5 text-[12px] font-normal text-faint">{t("platform.team.you")}</span>}
                      </div>
                      {m.name && <div className="truncate text-[12.5px] text-muted">{m.email}</div>}
                      <Badge tone={STATUS_TONE[m.status]} dot className="mt-1 sm:hidden">
                        {t(`platform.team.status.${m.status}`)}
                      </Badge>
                    </Td>
                    <Td>
                      {canManageUsers && !self && m.status !== "deactivated" ? (
                        <Select
                          aria-label={t("platform.team.roleOf", { member: m.email })}
                          value={roleValue(m)}
                          onChange={(e) => changeRole(m, e.target.value)}
                          className="w-30 max-w-full sm:w-40"
                        >
                          {roleOptions}
                        </Select>
                      ) : (
                        <span className="text-[13.5px]">{roleName(m)}</span>
                      )}
                    </Td>
                    <Td className="hidden sm:table-cell">
                      <Badge tone={STATUS_TONE[m.status]} dot>
                        {t(`platform.team.status.${m.status}`)}
                      </Badge>
                    </Td>
                    <Td className="hidden text-muted md:table-cell">
                      <Time iso={m.created_at} />
                    </Td>
                    {canManageUsers && (
                      <Td className="text-right">
                        {!self &&
                          (m.status === "deactivated" ? (
                            <Button size="sm" variant="ghost" onClick={() => setActive(m, true)} title={t("platform.team.reactivate")}>
                              <Icons.check className="size-4 sm:hidden" aria-hidden="true" />
                              <span className="sr-only sm:not-sr-only">{t("platform.team.reactivate")}</span>
                            </Button>
                          ) : (
                            <Button size="sm" variant="ghost" onClick={() => setDeactivating(m)} title={t("platform.team.deactivate")}>
                              <Icons.logout className="size-4 sm:hidden" aria-hidden="true" />
                              <span className="sr-only sm:not-sr-only">{t("platform.team.deactivate")}</span>
                            </Button>
                          ))}
                      </Td>
                    )}
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader
          title={t("platform.roles.title")}
          description={t("platform.roles.description")}
          actions={
            canManageRoles && (
              <Button onClick={() => setEditing("new")}>
                <Icons.plus className="size-4" /> {t("platform.roles.new")}
              </Button>
            )
          }
        />
        {roles.length === 0 ? (
          <EmptyState title={t("platform.roles.none")} description={t("platform.roles.noneHint")} />
        ) : (
          <ul className="divide-y divide-border">
            {roles.map((r) => (
              <li key={r.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-medium">{r.name}</span>
                    <Badge tone="accent">{t("platform.roles.basedOn", { role: t(r.base_role === "pm" ? "platform.team.rolePm" : "platform.team.roleClient") })}</Badge>
                    <span className="text-[12.5px] text-faint">{t("platform.roles.members", { count: r.members })}</span>
                  </div>
                  {r.description && <p className="mt-0.5 text-[13px] text-muted">{r.description}</p>}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {r.permissions.length === 0 ? (
                      <span className="text-[12.5px] text-faint">{t("platform.roles.noPermissions")}</span>
                    ) : (
                      r.permissions.map((p) => (
                        <Badge key={p} title={permLabel(p)}>
                          <span className="font-mono">{p}</span>
                        </Badge>
                      ))
                    )}
                  </div>
                </div>
                {canManageRoles && (
                  <Button size="sm" variant="ghost" onClick={() => setEditing(r)} className="self-start">
                    <Icons.edit className="size-4" /> {t("platform.common.edit")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Dialog open={inviteOpen} onClose={closeInvite} title={invited ? t("platform.team.invitedTitle") : t("platform.team.inviteTitle")}>
        {invited ? (
          <div className="space-y-4">
            {invited.email_sent ? (
              <Callout tone="ok">{t("platform.team.inviteEmailed", { email: invited.user.email })}</Callout>
            ) : (
              <Callout tone="warn" title={t("platform.team.noEmailTitle")}>
                {t("platform.team.noEmailBody")}
              </Callout>
            )}
            {invited.invite_url && <CopyField value={invited.invite_url} label={t("platform.team.inviteLink")} />}
            <div className="flex justify-end">
              <Button variant="primary" onClick={closeInvite}>
                {t("platform.common.done")}
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={sendInvite} className="space-y-4">
            <Field label={t("platform.team.email")}>
              {(id) => <Input id={id} type="email" required value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />}
            </Field>
            <Field label={t("platform.team.name")} hint={t("platform.common.optional")}>
              {(id, d) => <Input id={id} aria-describedby={d} value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} />}
            </Field>
            <Field label={t("platform.team.role")}>
              {(id) => (
                <Select id={id} value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
                  {roleOptions}
                </Select>
              )}
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={closeInvite}>
                {t("platform.common.cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={!invite.email.trim()}>
                {t("platform.team.sendInvite")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog
        open={deactivating !== null}
        onClose={() => setDeactivating(null)}
        size="sm"
        title={t("platform.team.deactivateTitle")}
        description={t("platform.team.deactivateBody", { member: deactivating?.email ?? "" })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeactivating(null)}>
              {t("platform.common.cancel")}
            </Button>
            <Button variant="danger" onClick={() => deactivating && setActive(deactivating, false)}>
              {t("platform.team.deactivate")}
            </Button>
          </>
        }
      />

      {editing !== null && (
        <RoleDialog
          role={editing === "new" ? null : editing}
          catalog={catalog}
          permLabel={permLabel}
          onClose={() => setEditing(null)}
          onSaved={(r) => {
            setRoles((xs) => (xs.some((x) => x.id === r.id) ? xs.map((x) => (x.id === r.id ? r : x)) : [...xs, r]));
            setEditing(null);
          }}
          onDelete={removeRole}
        />
      )}
    </div>
  );
}

function RoleDialog({
  role,
  catalog,
  permLabel,
  onClose,
  onSaved,
  onDelete,
}: {
  role: CustomRole | null;
  catalog: { key: string; description: string }[];
  permLabel: (key: string, fallback?: string) => string;
  onClose: () => void;
  onSaved: (r: CustomRole) => void;
  onDelete: (r: CustomRole) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [form, setForm] = useState<RoleInput>({
    name: role?.name ?? "",
    description: role?.description ?? "",
    base_role: role?.base_role ?? "client",
    permissions: role?.permissions ?? [],
  });
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Group the catalog by area ("jobs.read" -> "jobs") for a compact grid.
  const groups = useMemo(() => {
    const out: Record<string, { key: string; description: string }[]> = {};
    for (const p of catalog) (out[p.key.split(".")[0]] ??= []).push(p);
    return Object.entries(out);
  }, [catalog]);
  const extra = form.permissions.filter((p) => !catalog.some((c) => c.key === p));

  function toggle(key: string, on: boolean) {
    setForm((f) => ({ ...f, permissions: on ? [...f.permissions, key] : f.permissions.filter((p) => p !== key) }));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const out = role ? await api.updateRole(role.id, form) : await api.createRole(form);
      toast.success(t("platform.roles.saved"));
      onSaved(out);
    } catch (err) {
      toast.error(t("platform.roles.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onClose={onClose} size="lg" title={role ? t("platform.roles.editTitle") : t("platform.roles.newTitle")}>
      <form onSubmit={save} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("platform.roles.name")}>
            {(id) => <Input id={id} required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}
          </Field>
          <Field label={t("platform.roles.baseRole")} hint={t("platform.roles.baseRoleHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={form.base_role} onChange={(e) => setForm({ ...form, base_role: e.target.value as "pm" | "client" })}>
                <option value="client">{t("platform.team.roleClient")}</option>
                <option value="pm">{t("platform.team.rolePm")}</option>
              </Select>
            )}
          </Field>
        </div>
        <Field label={t("platform.roles.descriptionLabel")} hint={t("platform.common.optional")}>
          {(id, d) => (
            <Textarea id={id} aria-describedby={d} maxLength={500} className="min-h-14" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          )}
        </Field>
        <fieldset>
          <legend className="mb-1 text-[13px] font-medium">{t("platform.roles.permissions")}</legend>
          <p className="mb-2 text-[12.5px] text-muted">{t("platform.roles.permissionsHint")}</p>
          <div className="grid max-h-[42vh] gap-x-4 gap-y-3 overflow-y-auto rounded-md border border-border p-3 sm:grid-cols-2">
            {groups.map(([area, perms]) => (
              <div key={area}>
                <div className="mb-1 font-mono text-[11.5px] uppercase tracking-wide text-faint">{area}</div>
                <ul className="space-y-1">
                  {perms.map((p) => (
                    <li key={p.key}>
                      <label className="flex items-start gap-2 text-[13px]">
                        <input
                          type="checkbox"
                          className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
                          checked={form.permissions.includes(p.key)}
                          onChange={(e) => toggle(p.key, e.target.checked)}
                        />
                        <span className="min-w-0">
                          <span className="font-mono text-[12px] text-fg">{p.key}</span>
                          <span className="block text-[12.5px] text-muted">{permLabel(p.key, p.description)}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {extra.length > 0 && (
            <p className="mt-2 text-[12.5px] text-muted">
              {t("platform.roles.patterns")} <span className="font-mono">{extra.join(", ")}</span>
            </p>
          )}
        </fieldset>
        <div className="flex flex-wrap justify-end gap-2">
          {role &&
            (confirmDelete ? (
              <Button variant="danger" className="mr-auto" onClick={() => onDelete(role)}>
                {t("platform.roles.confirmDelete")}
              </Button>
            ) : (
              <Button variant="ghost" className="mr-auto" onClick={() => setConfirmDelete(true)} disabled={role.members > 0} title={role.members > 0 ? t("platform.roles.inUse") : undefined}>
                <Icons.trash className="size-4" /> {t("platform.roles.delete")}
              </Button>
            ))}
          <Button variant="ghost" onClick={onClose}>
            {t("platform.common.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!form.name.trim()}>
            {t("platform.roles.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
