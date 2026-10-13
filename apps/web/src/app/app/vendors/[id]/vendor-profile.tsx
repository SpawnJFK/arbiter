"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Icons } from "@/components/icons";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  RATE_UNITS,
  VENDOR_SERVICES,
  type AssignmentStatus,
  type RateUnit,
  type TimelineDay,
  type Vendor,
  type VendorInput,
  type VendorService,
} from "@/lib/vendor-types";
import { parsePairs } from "../vendor-form";

const TABS = [
  ["profile", k("app.vendors.detail.tabProfile")],
  ["rates", k("app.vendors.detail.tabRates")],
  ["availability", k("app.vendors.detail.tabAvailability")],
  ["assignments", k("app.vendors.detail.tabAssignments")],
  ["documents", k("app.vendors.detail.tabDocuments")],
] as const;
type Tab = (typeof TABS)[number][0];

const WEEKDAYS = [
  k("app.vendors.detail.mon"),
  k("app.vendors.detail.tue"),
  k("app.vendors.detail.wed"),
  k("app.vendors.detail.thu"),
  k("app.vendors.detail.fri"),
  k("app.vendors.detail.sat"),
  k("app.vendors.detail.sun"),
];

export const ASSIGNMENT_TONE: Record<AssignmentStatus, Tone> = {
  pending: "neutral",
  offered: "info",
  accepted: "accent",
  in_progress: "accent",
  delivered: "warn",
  approved: "ok",
  invoiced: "ok",
  declined: "neutral",
  expired: "neutral",
  withdrawn: "neutral",
  cancelled: "danger",
};

export function VendorProfile({ vendor }: { vendor: Vendor }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("profile");
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label={t("app.vendors.detail.sections")} className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px inline-flex h-9 items-center whitespace-nowrap border-b-2 px-3 text-[13.5px] transition-colors",
              tab === key ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            {t(label)}
          </button>
        ))}
      </div>
      {tab === "profile" && <ProfileTab vendor={vendor} />}
      {tab === "rates" && <RatesTab vendor={vendor} />}
      {tab === "availability" && <AvailabilityTab vendor={vendor} />}
      {tab === "assignments" && <AssignmentsTab vendor={vendor} />}
      {tab === "documents" && <DocumentsTab vendor={vendor} />}
    </div>
  );
}

function useSave(vendorId: string) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function save(body: Partial<VendorInput>) {
    setBusy(true);
    try {
      await api.updateVendor(vendorId, body);
      toast.success(t("app.vendors.detail.saved"));
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendors.detail.couldNotSave"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, save };
}

function ProfileTab({ vendor }: { vendor: Vendor }) {
  const { t } = useI18n();
  const { busy, save } = useSave(vendor.id);
  const [f, setF] = useState({
    name: vendor.name,
    email: vendor.email ?? "",
    phone: vendor.phone ?? "",
    country: vendor.country ?? "",
    status: vendor.status,
    rating: vendor.rating ?? "",
    legal_name: vendor.legal_name ?? "",
    tax_id: vendor.tax_id ?? "",
    address: vendor.address ?? "",
    iban: vendor.iban ?? "",
    swift: vendor.swift ?? "",
    payment_terms_days: String(vendor.payment_terms_days),
    domains: vendor.domains.join(", "),
    notes: vendor.notes,
  });
  const set = (key: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF((x) => ({ ...x, [key]: e.target.value }));
  const text = (key: keyof typeof f, label: string, extra: Partial<React.ComponentProps<typeof Input>> = {}) => (
    <Field label={label}>{(id) => <Input id={id} value={f[key]} onChange={set(key)} {...extra} />}</Field>
  );
  return (
    <Card>
      <CardHeader title={t("app.vendors.detail.contactAndPayment")} description={t("app.vendors.detail.contactAndPaymentHint")} />
      <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
        {text("name", t("app.vendors.form.name"))}
        {text("email", t("app.vendors.form.email"), { type: "email" })}
        {text("phone", t("app.vendors.detail.phone"))}
        {text("country", t("app.vendors.detail.country"), { maxLength: 2 })}
        <Field label={t("app.vendors.form.status")}>
          {(id) => (
            <Select id={id} value={f.status} onChange={set("status")}>
              <option value="active">{t("enum.active")}</option>
              <option value="inactive">{t("enum.inactive")}</option>
              <option value="blocked">{t("enum.blocked")}</option>
            </Select>
          )}
        </Field>
        {text("rating", t("app.vendors.detail.ratingHint"), { inputMode: "decimal" })}
        {text("legal_name", t("app.vendors.detail.legalName"))}
        {text("tax_id", t("app.vendors.detail.taxId"))}
        {text("address", t("app.vendors.detail.address"))}
        {text("iban", t("app.vendors.detail.iban"))}
        {text("swift", t("app.vendors.detail.swift"))}
        {text("payment_terms_days", t("app.vendors.detail.paymentTerms"), { inputMode: "numeric" })}
        <div className="sm:col-span-2 lg:col-span-3">{text("domains", t("app.vendors.detail.domains"))}</div>
        <Field label={t("app.vendors.detail.notes")} className="sm:col-span-2 lg:col-span-3">
          {(id) => <Textarea id={id} value={f.notes} onChange={set("notes")} />}
        </Field>
      </div>
      <div className="flex justify-end border-t border-border px-4 py-3">
        <Button
          variant="primary"
          loading={busy}
          onClick={() =>
            save({
              name: f.name.trim(),
              email: f.email.trim() || null,
              phone: f.phone.trim() || null,
              country: f.country.trim().toUpperCase() || null,
              status: f.status,
              rating: f.rating.trim() || null,
              legal_name: f.legal_name.trim() || null,
              tax_id: f.tax_id.trim() || null,
              address: f.address.trim() || null,
              iban: f.iban.trim() || null,
              swift: f.swift.trim() || null,
              payment_terms_days: Number(f.payment_terms_days) || 0,
              domains: f.domains.split(",").map((d) => d.trim()).filter(Boolean),
              notes: f.notes,
            })
          }
        >
          {t("app.vendors.detail.save")}
        </Button>
      </div>
    </Card>
  );
}

interface RateRow {
  service: VendorService;
  unit: RateUnit;
  source_lang: string;
  target_lang: string;
  rate: string;
}

function RatesTab({ vendor }: { vendor: Vendor }) {
  const { t } = useI18n();
  const { busy, save } = useSave(vendor.id);
  const [pairs, setPairs] = useState(vendor.pairs.map((p) => `${p.source_lang}>${p.target_lang}`).join(", "));
  const [services, setServices] = useState<VendorService[]>(
    vendor.pairs.length ? Array.from(new Set(vendor.pairs.flatMap((p) => p.services))) : ["translation", "review"],
  );
  const [rows, setRows] = useState<RateRow[]>(
    vendor.rates.map((r) => ({ service: r.service, unit: r.unit, source_lang: r.source_lang ?? "", target_lang: r.target_lang ?? "", rate: r.rate })),
  );
  const update = (i: number, patch: Partial<RateRow>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("app.vendors.detail.pairsTitle")} description={t("app.vendors.form.pairsHint")} />
        <div className="space-y-3 p-4">
          <Input aria-label={t("app.vendors.form.pairs")} value={pairs} onChange={(e) => setPairs(e.target.value)} />
          <div className="flex flex-wrap gap-4">
            {VENDOR_SERVICES.map((s) => (
              <Checkbox
                key={s}
                label={t.enumLabel(s)}
                checked={services.includes(s)}
                onChange={(e) => setServices((cur) => (e.target.checked ? [...cur, s] : cur.filter((x) => x !== s)))}
              />
            ))}
          </div>
        </div>
      </Card>
      <Card>
        <CardHeader
          title={t("app.vendors.detail.ratesTitle", { currency: vendor.currency })}
          description={t("app.vendors.detail.ratesHint")}
          actions={
            <Button size="sm" onClick={() => setRows((rs) => [...rs, { service: "translation", unit: "word", source_lang: "", target_lang: "", rate: "" }])}>
              <Icons.plus className="size-4" /> {t("app.vendors.detail.addRate")}
            </Button>
          }
        />
        {rows.length === 0 ? (
          <EmptyState title={t("app.vendors.detail.noRates")} description={t("app.vendors.detail.noRatesHint")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.vendors.detail.service")}</Th>
                <Th>{t("app.vendors.detail.unit")}</Th>
                <Th>{t("app.vendors.detail.source")}</Th>
                <Th>{t("app.vendors.detail.target")}</Th>
                <Th className="text-right">{t("app.vendors.detail.rate")}</Th>
                <Th />
              </tr>
            </THead>
            <TBody>
              {rows.map((r, i) => (
                <Tr key={i}>
                  <Td>
                    <Select aria-label={t("app.vendors.detail.service")} value={r.service} onChange={(e) => update(i, { service: e.target.value as VendorService })} className="w-36">
                      {VENDOR_SERVICES.map((s) => (
                        <option key={s} value={s}>
                          {t.enumLabel(s)}
                        </option>
                      ))}
                    </Select>
                  </Td>
                  <Td>
                    <Select aria-label={t("app.vendors.detail.unit")} value={r.unit} onChange={(e) => update(i, { unit: e.target.value as RateUnit })} className="w-32">
                      {RATE_UNITS.map((u) => (
                        <option key={u} value={u}>
                          {t.enumLabel(u)}
                        </option>
                      ))}
                    </Select>
                  </Td>
                  <Td>
                    <Input aria-label={t("app.vendors.detail.source")} value={r.source_lang} onChange={(e) => update(i, { source_lang: e.target.value })} placeholder={t("app.vendors.detail.any")} className="w-20" />
                  </Td>
                  <Td>
                    <Input aria-label={t("app.vendors.detail.target")} value={r.target_lang} onChange={(e) => update(i, { target_lang: e.target.value })} placeholder={t("app.vendors.detail.any")} className="w-20" />
                  </Td>
                  <Td className="text-right">
                    <Input aria-label={t("app.vendors.detail.rate")} inputMode="decimal" value={r.rate} onChange={(e) => update(i, { rate: e.target.value })} className="ml-auto w-24 text-right" />
                  </Td>
                  <Td className="text-right">
                    <Button size="sm" variant="ghost" aria-label={t("app.vendors.detail.removeRate")} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                      <Icons.trash className="size-4" />
                    </Button>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
        <div className="flex justify-end border-t border-border px-4 py-3">
          <Button
            variant="primary"
            loading={busy}
            onClick={() =>
              save({
                pairs: parsePairs(pairs, services),
                rates: rows
                  .filter((r) => r.rate.trim())
                  .map((r) => ({
                    service: r.service,
                    unit: r.unit,
                    source_lang: r.source_lang.trim().toLowerCase() || null,
                    target_lang: r.target_lang.trim().toLowerCase() || null,
                    rate: r.rate.trim().replace(",", "."),
                  })),
              })
            }
          >
            {t("app.vendors.detail.save")}
          </Button>
        </div>
      </Card>
    </div>
  );
}

function AvailabilityTab({ vendor }: { vendor: Vendor }) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const { busy, save } = useSave(vendor.id);
  const [capacity, setCapacity] = useState(String(vendor.capacity_words_per_day));
  const [days, setDays] = useState<number[]>(vendor.working_days);
  const [absence, setAbsence] = useState({ start_date: "", end_date: "", note: "" });
  const [calendar, setCalendar] = useState<TimelineDay[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .vendorCalendar(vendor.id, { days: 28 })
      .then((c) => alive && setCalendar(c.days))
      .catch(() => alive && setCalendar([]));
    return () => {
      alive = false;
    };
  }, [vendor.id, vendor.absences, vendor.capacity_words_per_day]);

  async function addAbsence() {
    try {
      await api.addAbsence(vendor.id, absence);
      setAbsence({ start_date: "", end_date: "", note: "" });
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendors.detail.couldNotSave"), errorMessage(e));
    }
  }
  async function removeAbsence(id: string) {
    try {
      await api.deleteAbsence(vendor.id, id);
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendors.detail.couldNotSave"), errorMessage(e));
    }
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card>
        <CardHeader title={t("app.vendors.detail.next4Weeks")} description={t("app.vendors.detail.calendarHint")} />
        <div className="p-4">
          {calendar === null ? (
            <p className="text-[13px] text-muted">{t("app.vendors.detail.loading")}</p>
          ) : (
            <ol className="grid grid-cols-7 gap-1.5" aria-label={t("app.vendors.detail.next4Weeks")}>
              {calendar.map((d) => {
                const share = d.capacity > 0 ? Math.min(1, d.load / d.capacity) : 0;
                return (
                  <li
                    key={d.date}
                    title={t("app.vendors.detail.dayTitle", { date: d.date, load: d.load, capacity: d.capacity })}
                    className={cn(
                      "rounded-md border px-1.5 py-1 text-[11.5px]",
                      d.absent ? "border-warn/40 bg-warn-subtle" : d.capacity === 0 ? "border-border bg-subtle" : "border-border bg-surface",
                    )}
                  >
                    <div className="tabular font-medium">{f.dateOnly(d.date).replace(/,? \d{4}$/, "")}</div>
                    {d.absent ? (
                      <div className="text-warn">{t("app.vendors.detail.absent")}</div>
                    ) : d.capacity === 0 ? (
                      <div className="text-faint">{t("app.vendors.detail.off")}</div>
                    ) : (
                      <>
                        <div className="tabular text-muted">{t("app.vendors.detail.freeWords", { free: f.num(d.free) })}</div>
                        <div className="mt-1 h-1 overflow-hidden rounded-full bg-subtle">
                          <div className={cn("h-full rounded-full", share >= 1 ? "bg-danger" : share > 0.7 ? "bg-warn" : "bg-accent")} style={{ width: `${Math.round(share * 100)}%` }} />
                        </div>
                      </>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title={t("app.vendors.detail.weeklyCapacity")} />
          <div className="space-y-3 p-4">
            <Field label={t("app.vendors.form.capacity")}>
              {(id) => <Input id={id} inputMode="numeric" value={capacity} onChange={(e) => setCapacity(e.target.value)} />}
            </Field>
            <div role="group" aria-label={t("app.vendors.detail.workingDays")} className="flex flex-wrap gap-1">
              {WEEKDAYS.map((label, i) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={days.includes(i)}
                  onClick={() => setDays((cur) => (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort()))}
                  className={cn(
                    "h-7 rounded-md border px-2 text-[12.5px]",
                    days.includes(i) ? "border-accent bg-accent-subtle text-accent" : "border-border-strong text-muted hover:text-fg",
                  )}
                >
                  {t(label)}
                </button>
              ))}
            </div>
            <Button variant="primary" size="sm" loading={busy} onClick={() => save({ capacity_words_per_day: Number(capacity) || 0, working_days: days })}>
              {t("app.vendors.detail.save")}
            </Button>
          </div>
        </Card>
        <Card>
          <CardHeader title={t("app.vendors.detail.absences")} />
          <ul className="divide-y divide-border">
            {(vendor.absences ?? []).map((a) => (
              <li key={a.id} className="flex items-center gap-2 px-4 py-2 text-[13px]">
                <span className="tabular">
                  {a.start_date} → {a.end_date}
                </span>
                <span className="min-w-0 flex-1 truncate text-muted">{a.note}</span>
                <Button size="sm" variant="ghost" aria-label={t("app.vendors.detail.removeAbsence")} onClick={() => removeAbsence(a.id)}>
                  <Icons.trash className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
          <div className="grid gap-2 border-t border-border p-4 sm:grid-cols-2">
            <Field label={t("app.vendors.detail.from")}>
              {(id) => <Input id={id} type="date" value={absence.start_date} onChange={(e) => setAbsence((a) => ({ ...a, start_date: e.target.value }))} />}
            </Field>
            <Field label={t("app.vendors.detail.to")}>
              {(id) => <Input id={id} type="date" value={absence.end_date} onChange={(e) => setAbsence((a) => ({ ...a, end_date: e.target.value }))} />}
            </Field>
            <Field label={t("app.vendors.detail.note")} className="sm:col-span-2">
              {(id) => <Input id={id} value={absence.note} onChange={(e) => setAbsence((a) => ({ ...a, note: e.target.value }))} />}
            </Field>
            <Button size="sm" onClick={addAbsence} disabled={!absence.start_date || !absence.end_date} className="sm:col-span-2">
              <Icons.plus className="size-4" /> {t("app.vendors.detail.addAbsence")}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function AssignmentsTab({ vendor }: { vendor: Vendor }) {
  const { f, t } = useI18n();
  const rows = vendor.assignments ?? [];
  return (
    <Card>
      {rows.length === 0 ? (
        <EmptyState title={t("app.vendors.detail.noAssignments")} description={t("app.vendors.detail.noAssignmentsHint")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("app.vendors.detail.job")}</Th>
              <Th>{t("app.vendors.detail.step")}</Th>
              <Th>{t("app.vendors.detail.status")}</Th>
              <Th className="text-right">{t("app.vendors.detail.words")}</Th>
              <Th className="text-right">{t("app.vendors.detail.amount")}</Th>
              <Th className="hidden md:table-cell">{t("app.vendors.detail.po")}</Th>
              <Th className="hidden lg:table-cell">{t("app.vendors.detail.due")}</Th>
            </tr>
          </THead>
          <TBody>
            {rows.map((a) => (
              <Tr key={a.id}>
                <Td>
                  <Link href={`/app/jobs/${a.job_id}`} className="font-mono text-[12.5px] hover:text-accent hover:underline">
                    {a.job_id}
                  </Link>
                </Td>
                <Td className="text-[13px]">{t.enumLabel(a.step)}</Td>
                <Td>
                  <Badge tone={ASSIGNMENT_TONE[a.status]}>{t.enumLabel(a.status)}</Badge>
                </Td>
                <Td className="tabular text-right">
                  {f.num(a.words_done)} / {f.num(a.words)}
                </Td>
                <Td className="tabular text-right">{f.money(a.amount, a.currency)}</Td>
                <Td className="hidden font-mono text-[12.5px] md:table-cell">{a.po_number ?? "–"}</Td>
                <Td className="hidden text-[13px] text-muted lg:table-cell">{a.due_at ? f.dateTime(a.due_at) : "–"}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

function DocumentsTab({ vendor }: { vendor: Vendor }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [doc, setDoc] = useState({ kind: "nda", title: "", signed: true, signed_at: "" });
  async function add() {
    try {
      await api.addVendorDocument(vendor.id, { ...doc, signed_at: doc.signed_at || undefined });
      setDoc({ kind: "nda", title: "", signed: true, signed_at: "" });
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendors.detail.couldNotSave"), errorMessage(e));
    }
  }
  async function remove(id: string) {
    try {
      await api.deleteVendorDocument(vendor.id, id);
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendors.detail.couldNotSave"), errorMessage(e));
    }
  }
  const docs = vendor.documents ?? [];
  return (
    <Card>
      <CardHeader
        title={t("app.vendors.detail.documents")}
        description={vendor.nda_signed ? t("app.vendors.detail.ndaSignedOn", { date: vendor.nda_signed_at ?? "" }) : t("app.vendors.detail.noNda")}
      />
      {docs.length > 0 && (
        <ul className="divide-y divide-border">
          {docs.map((d) => (
            <li key={d.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
              <Badge>{t.enumLabel(d.kind)}</Badge>
              <span className="min-w-0 flex-1 truncate font-medium">{d.title}</span>
              <span className="text-muted">{d.signed ? t("app.vendors.detail.signedOn", { date: d.signed_at ?? "" }) : t("app.vendors.detail.notSigned")}</span>
              <Button size="sm" variant="ghost" aria-label={t("app.vendors.detail.removeDocument")} onClick={() => remove(d.id)}>
                <Icons.trash className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-3 border-t border-border p-4 sm:grid-cols-4 sm:items-end">
        <Field label={t("app.vendors.detail.docKind")}>
          {(id) => (
            <Select id={id} value={doc.kind} onChange={(e) => setDoc((d) => ({ ...d, kind: e.target.value }))}>
              <option value="nda">{t("enum.nda")}</option>
              <option value="contract">{t("enum.contract")}</option>
              <option value="certificate">{t("enum.certificate")}</option>
              <option value="other">{t("enum.other")}</option>
            </Select>
          )}
        </Field>
        <Field label={t("app.vendors.detail.docTitle")}>
          {(id) => <Input id={id} value={doc.title} onChange={(e) => setDoc((d) => ({ ...d, title: e.target.value }))} />}
        </Field>
        <Field label={t("app.vendors.detail.signedAt")}>
          {(id) => <Input id={id} type="date" value={doc.signed_at} onChange={(e) => setDoc((d) => ({ ...d, signed_at: e.target.value }))} />}
        </Field>
        <Button onClick={add} disabled={!doc.title.trim()}>
          <Icons.plus className="size-4" /> {t("app.vendors.detail.addDocument")}
        </Button>
      </div>
    </Card>
  );
}
