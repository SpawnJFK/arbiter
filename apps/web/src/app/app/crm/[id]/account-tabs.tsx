"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { isPast } from "@/lib/format";
import { ACTIVITY_KINDS, DEAL_STAGES, type AccountDetail, type Activity, type ActivityKind, type DealStage, type PriceList, type Project, type Workflow } from "@/lib/types";
import { AccountForm } from "../account-form";

const TABS = ["activities", "contacts", "deals", "projects", "settings"] as const;
type Tab = (typeof TABS)[number];

export const ACTIVITY_ICON: Record<ActivityKind, keyof typeof Icons> = { note: "note", call: "phone", email: "mail", meeting: "calendar", task: "checklist" };

export function AccountTabs({
  account,
  workflows,
  priceLists,
  projects,
  initialTab,
}: {
  account: AccountDetail;
  workflows: Workflow[];
  priceLists: PriceList[];
  projects: Project[];
  initialTab?: string;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>(TABS.find((tab) => tab === initialTab) ?? "activities");
  const counts: Partial<Record<Tab, number>> = { contacts: account.contacts.length, deals: account.deals.length, projects: projects.length };
  return (
    <>
      <div role="tablist" aria-label={t("app.crm.detail.accountTabs.accountSections")} className="mb-4 flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((section) => (
          <button
            key={section}
            role="tab"
            id={`tab-${section}`}
            aria-selected={tab === section}
            aria-controls={`panel-${section}`}
            onClick={() => setTab(section)}
            className={cn("-mb-px inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-[13.5px]", tab === section ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg")}
          >
            {t.enumLabel(section)}
            {counts[section] !== undefined && <span className="tabular rounded bg-subtle px-1.5 text-[11.5px] text-muted">{counts[section]}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "activities" && <Activities account={account} />}
        {tab === "contacts" && <Contacts account={account} />}
        {tab === "deals" && <Deals account={account} />}
        {tab === "projects" && <Projects projects={projects} accountId={account.id} />}
        {tab === "settings" && <Settings account={account} workflows={workflows} priceLists={priceLists} />}
      </div>
    </>
  );
}

function Activities({ account }: { account: AccountDetail }) {
  const { t } = useI18n();
  const toast = useToast();
  const [items, setItems] = useState<Activity[]>(account.recent_activities);
  const [kind, setKind] = useState<ActivityKind>("note");
  const [body, setBody] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    try {
      const a = await api.createActivity({ account_id: account.id, kind, body: body.trim(), due_at: due ? new Date(due).toISOString() : undefined });
      setItems((xs) => [a, ...xs]);
      setBody("");
      setDue("");
    } catch (err) {
      toast.error(t("app.crm.detail.accountTabs.couldNotAdd"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function toggle(a: Activity) {
    try {
      const u = await api.updateActivity(a.id, { done: !a.done });
      setItems((xs) => xs.map((x) => (x.id === a.id ? u : x)));
    } catch (err) {
      toast.error(t("app.crm.detail.accountTabs.couldNotUpdate"), errorMessage(err));
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <Card className="order-2 lg:order-1">
        {items.length === 0 ? (
          <EmptyState title={t("app.crm.detail.accountTabs.noActivityYet")} description={t("app.crm.detail.accountTabs.logCallsMeetingsAndNotes")} />
        ) : (
          <ol className="px-4 py-2">
            {items.map((a, i) => {
              const Icon = Icons[ACTIVITY_ICON[a.kind] ?? "note"];
              const overdue = !a.done && isPast(a.due_at);
              return (
                <li key={a.id} className="relative flex gap-3 py-3">
                  {i < items.length - 1 && <span className="absolute left-[13px] top-10 bottom-0 w-px bg-border" aria-hidden="true" />}
                  <span className={cn("relative flex size-7 shrink-0 items-center justify-center rounded-full", a.done ? "bg-subtle text-faint" : "bg-accent-subtle text-accent")}>
                    <Icon className="size-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                      <span className="font-medium text-fg">{t.enumLabel(a.kind)}</span>
                      <Time iso={a.created_at} mode="relative" />
                      {a.due_at && (
                        <Badge tone={a.done ? "neutral" : overdue ? "danger" : "warn"}>
                          {t("app.crm.detail.accountTabs.due")} <Time iso={a.due_at} mode="relative" />
                        </Badge>
                      )}
                      {a.done && <Badge tone="ok">{t("app.crm.detail.accountTabs.done")}</Badge>}
                    </div>
                    <p className={cn("mt-0.5 whitespace-pre-wrap text-[14px]", a.done && a.kind === "task" && "text-muted line-through")}>{a.body}</p>
                  </div>
                  {(a.kind === "task" || a.due_at) && (
                    <Button size="sm" variant={a.done ? "ghost" : "secondary"} onClick={() => toggle(a)} aria-label={a.done ? t("app.crm.detail.accountTabs.reopen") : t("app.crm.detail.accountTabs.markDone")}>
                      {a.done ? t("app.crm.detail.accountTabs.reopen") : (
                        <>
                          <Icons.check className="size-3.5" /> {t("app.crm.detail.accountTabs.done")}
                        </>
                      )}
                    </Button>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </Card>
      <Card className="order-1 self-start p-4 lg:order-2">
        <form onSubmit={add} className="space-y-3">
          <div role="group" aria-label={t("app.crm.detail.accountTabs.activityKind")} className="flex flex-wrap gap-1">
            {ACTIVITY_KINDS.map((k) => {
              const Icon = Icons[ACTIVITY_ICON[k]];
              return (
                <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)} className={cn("inline-flex h-7 items-center gap-1 rounded-md border px-2 text-[12.5px]", kind === k ? "border-accent bg-accent-subtle text-accent" : "border-border text-muted hover:bg-hover")}>
                  <Icon className="size-3.5" /> {t.enumLabel(k)}
                </button>
              );
            })}
          </div>
          <Textarea aria-label={t("app.crm.detail.accountTabs.activityText")} placeholder={kind === "task" ? t("app.crm.detail.accountTabs.whatNeedsDoing") : kind === "call" ? t("app.crm.detail.accountTabs.whatWasDiscussed") : t("app.crm.detail.accountTabs.writeANote")} value={body} onChange={(e) => setBody(e.target.value)} className="min-h-20" />
          {(kind === "task" || kind === "meeting") && (
            <Field label={t("app.crm.detail.accountTabs.due")}>{(id) => <Input id={id} type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />}</Field>
          )}
          <Button type="submit" variant="primary" loading={busy} disabled={!body.trim()} className="w-full">
            {t("app.crm.detail.accountTabs.add", { kind: kind })}
          </Button>
        </form>
      </Card>
    </div>
  );
}

function Contacts({ account }: { account: AccountDetail }) {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState({ name: "", email: "", phone: "", role: "", is_primary: account.contacts.length === 0 });
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createContact(account.id, { name: v.name, email: v.email || null, phone: v.phone || null, role: v.role || null, is_primary: v.is_primary });
      toast.success(t("app.crm.detail.accountTabs.contactAdded"));
      setOpen(false);
      router.refresh();
    } catch (err) {
      toast.error(t("app.crm.detail.accountTabs.couldNotAddContact"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    try {
      await api.deleteContact(id);
      router.refresh();
    } catch (err) {
      toast.error(t("app.crm.detail.accountTabs.couldNotRemove"), errorMessage(err));
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold">{t("app.crm.detail.accountTabs.contacts")}</h2>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Icons.plus className="size-3.5" /> {t("app.crm.detail.accountTabs.addContact")}
        </Button>
      </div>
      {account.contacts.length === 0 ? (
        <EmptyState title={t("app.crm.detail.accountTabs.noContacts")} description={t("app.crm.detail.accountTabs.addThePeopleYouWork")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("app.crm.detail.accountTabs.name")}</Th>
              <Th>{t("app.crm.detail.accountTabs.role")}</Th>
              <Th>{t("app.crm.detail.accountTabs.email")}</Th>
              <Th className="hidden md:table-cell">{t("app.crm.detail.accountTabs.phone")}</Th>
              <Th className="text-right">
                <span className="sr-only">{t("app.crm.detail.accountTabs.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {account.contacts.map((c) => (
              <Tr key={c.id}>
                <Td className="font-medium">
                  {c.name} {c.is_primary && <Badge tone="accent">{t("app.crm.detail.accountTabs.primary")}</Badge>}
                </Td>
                <Td className="text-muted">{c.role ?? "–"}</Td>
                <Td>{c.email ? <a href={`mailto:${c.email}`} className="text-accent hover:underline">{c.email}</a> : "–"}</Td>
                <Td className="hidden text-muted md:table-cell">{c.phone ?? "–"}</Td>
                <Td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => remove(c.id)} aria-label={t("app.crm.detail.accountTabs.remove", { name: c.name })}>
                    <Icons.trash className="size-3.5" />
                  </Button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title={t("app.crm.detail.accountTabs.addContact")}>
        <form onSubmit={add} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("app.crm.detail.accountTabs.name")}>{(id) => <Input id={id} required value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
            <Field label={t("app.crm.detail.accountTabs.role")}>{(id) => <Input id={id} value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })} placeholder={t("app.crm.detail.accountTabs.eGLocalizationLead")} />}</Field>
            <Field label={t("app.crm.detail.accountTabs.email")}>{(id) => <Input id={id} type="email" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />}</Field>
            <Field label={t("app.crm.detail.accountTabs.phone")}>{(id) => <Input id={id} type="tel" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
          </div>
          <Checkbox label={t("app.crm.detail.accountTabs.primaryContact")} checked={v.is_primary} onChange={(e) => setV({ ...v, is_primary: e.target.checked })} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("app.crm.detail.accountTabs.cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={busy}>
              {t("app.crm.detail.accountTabs.addContact")}
            </Button>
          </div>
        </form>
      </Dialog>
    </Card>
  );
}

function Deals({ account }: { account: AccountDetail }) {
  const { f, t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState({ title: "", value: "", stage: "lead" as DealStage, expected_close: "" });
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createDeal({ account_id: account.id, title: v.title, value: v.value || "0", stage: v.stage, expected_close: v.expected_close || undefined, currency: account.currency ?? undefined });
      toast.success(t("app.crm.detail.accountTabs.dealCreated"));
      setOpen(false);
      router.refresh();
    } catch (err) {
      toast.error(t("app.crm.detail.accountTabs.couldNotCreateDeal"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold">{t("app.crm.detail.accountTabs.deals")}</h2>
        <div className="flex gap-2">
          <Link href="/app/crm/deals" className="inline-flex h-7 items-center px-2 text-[13px] text-accent hover:underline">
            {t("app.crm.detail.accountTabs.dealBoard")}
          </Link>
          <Button size="sm" onClick={() => setOpen(true)}>
            <Icons.plus className="size-3.5" /> {t("app.crm.detail.accountTabs.newDeal")}
          </Button>
        </div>
      </div>
      {account.deals.length === 0 ? (
        <EmptyState title={t("app.crm.detail.accountTabs.noDeals")} description={t("app.crm.detail.accountTabs.trackOpportunitiesFromLeadTo")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("app.crm.detail.accountTabs.deal")}</Th>
              <Th>{t("app.crm.detail.accountTabs.stage")}</Th>
              <Th className="text-right">{t("app.crm.detail.accountTabs.value")}</Th>
              <Th className="hidden sm:table-cell">{t("app.crm.detail.accountTabs.expectedClose")}</Th>
            </tr>
          </THead>
          <TBody>
            {account.deals.map((d) => (
              <Tr key={d.id}>
                <Td className="font-medium">{d.title}</Td>
                <Td>
                  <Badge tone={d.stage === "won" ? "ok" : d.stage === "lost" ? "danger" : "accent"}>{t.enumLabel(d.stage)}</Badge>
                </Td>
                <Td className="tabular text-right">{f.money(d.value, d.currency)}</Td>
                <Td className="hidden text-muted sm:table-cell">{d.expected_close ? <Time iso={d.expected_close} mode="relative" /> : "–"}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title={t("app.crm.detail.accountTabs.newDeal")}>
        <form onSubmit={add} className="space-y-4">
          <Field label={t("app.crm.detail.accountTabs.title")}>{(id) => <Input id={id} required value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />}</Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t("app.crm.detail.accountTabs.valueInCurrency", { currency: account.currency ?? "EUR" })}>{(id) => <Input id={id} required inputMode="decimal" pattern="\d+(\.\d{1,2})?" value={v.value} onChange={(e) => setV({ ...v, value: e.target.value })} />}</Field>
            <Field label={t("app.crm.detail.accountTabs.stage")}>
              {(id) => (
                <Select id={id} value={v.stage} onChange={(e) => setV({ ...v, stage: e.target.value as DealStage })}>
                  {DEAL_STAGES.map((s) => (
                    <option key={s} value={s}>
                      {t.enumLabel(s)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("app.crm.detail.accountTabs.expectedClose")}>{(id) => <Input id={id} type="date" value={v.expected_close} onChange={(e) => setV({ ...v, expected_close: e.target.value })} />}</Field>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("app.crm.detail.accountTabs.cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={busy}>
              {t("app.crm.detail.accountTabs.createDeal")}
            </Button>
          </div>
        </form>
      </Dialog>
    </Card>
  );
}

function Projects({ projects, accountId }: { projects: Project[]; accountId: string }) {
  const { t } = useI18n();
  return (
    <Card>
      {projects.length === 0 ? (
        <EmptyState
          title={t("app.crm.detail.accountTabs.noProjectsYet")}
          description={t("app.crm.detail.accountTabs.projectsStartedForThisAccount")}
          action={
            <Link href={`/app/projects/new?account=${accountId}`} className="text-[13.5px] font-medium text-accent hover:underline">
              {t("app.crm.detail.accountTabs.startAProject")}
            </Link>
          }
        />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("app.crm.detail.accountTabs.project")}</Th>
              <Th>{t("app.crm.detail.accountTabs.languages")}</Th>
              <Th>{t("app.crm.detail.accountTabs.tier")}</Th>
              <Th className="hidden sm:table-cell">{t("app.crm.detail.accountTabs.created")}</Th>
            </tr>
          </THead>
          <TBody>
            {projects.map((p) => (
              <Tr key={p.id}>
                <Td>
                  <Link href={`/app/projects/${p.id}`} className="font-medium hover:text-accent hover:underline">
                    {p.name}
                  </Link>
                </Td>
                <Td className="font-mono text-[12.5px] text-muted">
                  {p.source_lang} → {p.target_langs.join(", ")}
                </Td>
                <Td>{t(`tier.${p.tier}.label`)}</Td>
                <Td className="hidden text-muted sm:table-cell">
                  <Time iso={p.created_at} mode="relative" />
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

function Settings({ account, workflows, priceLists }: { account: AccountDetail; workflows: Workflow[]; priceLists: PriceList[] }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  async function archive() {
    try {
      await api.archiveAccount(account.id);
      toast.success(t("app.crm.detail.accountTabs.accountArchived"));
      router.push("/app/crm");
    } catch (err) {
      toast.error(t("app.crm.detail.accountTabs.couldNotArchive"), errorMessage(err));
    }
  }
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <AccountForm account={account} workflows={workflows} priceLists={priceLists} />
      </Card>
      {account.status === "active" && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <h2 className="text-sm font-semibold">{t("app.crm.detail.accountTabs.archiveAccount")}</h2>
            <p className="text-[13px] text-muted">{t("app.crm.detail.accountTabs.hidesItFromListsProjects")}</p>
          </div>
          <Button variant="outline-danger" onClick={() => setConfirm(true)}>
            {t("app.crm.detail.accountTabs.archive")}
          </Button>
        </Card>
      )}
      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        size="sm"
        title={t("app.crm.detail.accountTabs.archive2", { name: account.name })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              {t("app.crm.detail.accountTabs.cancel")}
            </Button>
            <Button variant="danger" onClick={archive}>
              {t("app.crm.detail.accountTabs.archive")}
            </Button>
          </>
        }
      />
    </div>
  );
}
