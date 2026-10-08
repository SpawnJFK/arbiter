"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { BarChart, Delta, LineChart } from "@/components/charts";
import { Icons } from "@/components/icons";
import { Badge, JobStateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { LOWER_IS_BETTER, metricLabel, METRICS, widgetTypeLabel } from "@/lib/dashboard";
import type { Formatters } from "@/lib/i18n/format";
import type { Dashboard, DashboardData, DashboardPeriod, JobState, KpiData, PipelineData, SeriesData, TableData, Widget, WidgetSize, WidgetType } from "@/lib/types";

const PERIODS: DashboardPeriod[] = ["30d", "90d", "365d"];
const SPAN: Record<WidgetSize, string> = { s: "col-span-12 sm:col-span-6 lg:col-span-2", m: "col-span-12 lg:col-span-6", l: "col-span-12" };

export function DashboardView({
  dashboard,
  dashboards = [],
  data,
  period,
  canEdit,
}: {
  dashboard: Dashboard;
  dashboards?: Dashboard[];
  data: DashboardData;
  period: DashboardPeriod;
  canEdit: boolean;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const href = (p: DashboardPeriod, id = dashboard.id) => {
    const sp = new URLSearchParams();
    if (p !== "30d") sp.set("period", p);
    const target = dashboards.find((x) => x.id === id) ?? dashboard;
    if (!target.is_default) sp.set("dashboard", id);
    return `/app${sp.size ? `?${sp}` : ""}`;
  };
  const [editing, setEditing] = useState(false);
  const currency = data.currency ?? "EUR";
  const byId = new Map(data.widgets.map((w) => [w.id, w]));

  return (
    <>
      <PageHeader
        title={dashboard.name}
        description={t("app.dashboardView.lastKpiChangesCompareWith", { period: t(`app.dashboardView.period.${period}`) })}
        actions={
          <>
            {dashboards.length > 1 && (
              <Select aria-label={t("app.dashboardView.dashboard")} value={dashboard.id} onChange={(e) => router.push(href(period, e.target.value))} className="w-52">
                {dashboards.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                    {d.is_default ? t("app.dashboardView.default") : ""}
                  </option>
                ))}
              </Select>
            )}
            <div role="group" aria-label={t("app.dashboardView.period")} className="flex rounded-md border border-border-strong bg-surface p-0.5 shadow-card">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={p === period}
                  onClick={() => router.push(href(p))}
                  className={cn("h-7 rounded px-2.5 text-[13px]", p === period ? "bg-accent text-accent-fg" : "text-muted hover:text-fg")}
                >
                  {p}
                </button>
              ))}
            </div>
            {canEdit && !editing && (
              <Button onClick={() => setEditing(true)}>
                <Icons.edit className="size-3.5" /> {t("app.dashboardView.editDashboard")}
              </Button>
            )}
          </>
        }
      />
      {editing ? (
        <DashboardEditor dashboard={dashboard} onDone={() => setEditing(false)} />
      ) : dashboard.widgets.length === 0 ? (
        <Card>
          <EmptyState title={t("app.dashboardView.noWidgets")} description={t("app.dashboardView.addKpisChartsAndTables")} action={canEdit ? <Button onClick={() => setEditing(true)}>{t("app.dashboardView.editDashboard")}</Button> : undefined} />
        </Card>
      ) : (
        <div className="grid grid-cols-12 gap-3">
          {dashboard.widgets.map((w) => {
            const d = byId.get(w.id);
            return (
              <div key={w.id} className={SPAN[w.size ?? (w.type === "kpi" ? "s" : "m")]}>
                <WidgetCard widget={w} title={d?.title ?? w.title ?? metricLabel(t, w.metric)} data={d?.data ?? null} currency={currency} />
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

function fmtUnit(f: Formatters, unit: string, currency: string) {
  return (v: number | string | null | undefined): string => {
    if (v === null || v === undefined) return "–";
    const n = typeof v === "number" ? v : Number(v);
    if (unit === "ratio") return f.pct(n, 1);
    if (unit === "%") return f.pct(n / 100, 1);
    if (unit === "jobs" || unit === "words") return f.num(n);
    if (/^[A-Z]{3}$/.test(unit)) return f.money(n, unit);
    if (unit === "currency") return f.money(n, currency);
    return f.num(n);
  };
}

function compact(f: Formatters, unit: string) {
  const short = new Intl.NumberFormat(f.locale, { notation: "compact", maximumFractionDigits: 1 });
  return (n: number) => (unit === "ratio" ? f.pct(n, 0) : short.format(n));
}

function WidgetCard({ widget, title, data, currency }: { widget: Widget; title: string; data: unknown; currency: string }) {
  const { f, t } = useI18n();
  if (widget.type === "kpi") {
    const d = (data ?? { value: null, unit: "" }) as KpiData;
    const fmt = fmtUnit(f, d.unit, currency);
    const v = d.value === null || d.value === undefined ? null : Number(d.value);
    const prev = d.previous === null || d.previous === undefined ? null : Number(d.previous);
    return (
      <Card className="h-full px-4 py-3">
        <div className="text-[12.5px] text-muted">{title}</div>
        <div className="tabular mt-1 text-xl font-semibold tracking-tight">{fmt(d.value)}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-faint">
          <Delta value={v} previous={prev} invert={LOWER_IS_BETTER.has(widget.metric)} />
          {prev !== null ? <span>{t("app.dashboardView.vs", { previous: fmt(d.previous) })}</span> : d.count !== undefined ? <span>{t("app.dashboardView.open", { count: f.num(d.count) })}</span> : <span>{t("app.dashboardView.text")}</span>}
        </div>
      </Card>
    );
  }
  return (
    <Card className="h-full">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="text-[13.5px] font-semibold">{title}</h2>
      </div>
      <div className="p-3">
        {!data ? (
          <p className="px-1 py-6 text-center text-[13px] text-muted">{t("app.dashboardView.noData")}</p>
        ) : widget.type === "bar" || widget.type === "line" ? (
          <SeriesWidget type={widget.type} data={data as SeriesData} currency={currency} wide={widget.size === "l"} />
        ) : widget.type === "pipeline" ? (
          <PipelineWidget data={data as PipelineData} />
        ) : (
          <TableWidget metric={widget.metric} data={data as TableData} currency={currency} />
        )}
      </div>
    </Card>
  );
}

function SeriesWidget({ type, data, currency, wide }: { type: "bar" | "line"; data: SeriesData; currency: string; wide?: boolean }) {
  const { t, f } = useI18n();
  const points = data.points.map((p) => ({ label: t.enumLabel(p.label), value: p.value === null ? null : Number(p.value) }));
  if (points.length === 0 || points.every((p) => !p.value)) return <p className="px-1 py-10 text-center text-[13px] text-muted">{t("app.dashboardView.nothingInThisPeriodYet")}</p>;
  const unit = data.unit === currency ? currency : data.unit;
  const fmt = compact(f, unit);
  const size = wide ? { width: 1200, height: 240 } : { width: 600, height: 200 };
  return type === "bar" ? <BarChart points={points} format={fmt} {...size} /> : <LineChart points={points} format={fmt} {...size} />;
}

const STAGE_TONE: Record<string, string> = {
  lead: "bg-border-strong",
  qualified: "bg-info",
  proposal: "bg-accent",
  negotiation: "bg-violet",
  won: "bg-ok",
  lost: "bg-danger/60",
};

function PipelineWidget({ data }: { data: PipelineData }) {
  const { f, t } = useI18n();
  const max = Math.max(1, ...data.stages.map((s) => Number(s.value ?? 0)));
  return (
    <ul className="space-y-2 px-1 py-1">
      {data.stages.map((s) => (
        <li key={s.stage} className="grid grid-cols-[88px_1fr_auto] items-center gap-3 text-[13px]">
          <span className="text-muted">{t.enumLabel(s.stage)}</span>
          <div className="h-2 overflow-hidden rounded-full bg-subtle">
            <div className={cn("h-full rounded-full", STAGE_TONE[s.stage] ?? "bg-accent")} style={{ width: `${(Number(s.value ?? 0) / max) * 100}%` }} />
          </div>
          <span className="tabular w-36 text-right">
            <span className="font-medium">{s.value === null ? "–" : f.money(s.value, data.currency)}</span>
            <span className="ml-1.5 text-faint">· {s.count}</span>
          </span>
        </li>
      ))}
      <li className="pt-1 text-right">
        <Link href="/app/crm/deals" className="text-[12.5px] font-medium text-accent hover:underline">
          {t("app.dashboardView.openTheDealBoard")}
        </Link>
      </li>
    </ul>
  );
}

const HIDDEN = new Set(["id", "account_id"]);

function TableWidget({ metric, data, currency }: { metric: string; data: TableData; currency: string }) {
  const { t } = useI18n();
  const cols = data.columns.filter((c) => !HIDDEN.has(c) && !(metric === "overdue_jobs" && c === "due_at"));
  if (data.rows.length === 0)
    return (
      <p className="px-1 py-6 text-center text-[13px] text-muted">
        {metric === "overdue_jobs" ? t("app.dashboardView.nothingOverdue") : metric === "open_activities" ? t("app.dashboardView.noOpenActivities") : t("app.dashboardView.nothingInThisPeriodYet")}
      </p>
    );
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="text-[12px] text-muted">
            {cols.map((c) => (
              <th key={c} scope="col" className={cn("px-2 pb-1.5 font-medium", ["revenue", "margin", "jobs", "words", "hours_overdue"].includes(c) && "text-right")}>
                {c === "overdue" ? "" : t.has(`app.dashboardView.column.${c}`) ? t(`app.dashboardView.column.${c}`) : t.enumLabel(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.rows.slice(0, 8).map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c} className={cn("px-2 py-1.5 align-top", ["revenue", "margin", "jobs", "words", "hours_overdue"].includes(c) && "tabular text-right")}>
                  <Cell col={c} row={r} currency={currency} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Cell({ col, row, currency }: { col: string; row: Record<string, unknown>; currency: string }) {
  const { f, t } = useI18n();
  const v = row[col];
  if (v === null || v === undefined || v === "") return <span className="text-faint">–</span>;
  switch (col) {
    case "job_id":
      return (
        <Link href={`/app/jobs/${String(v)}`} className="font-mono text-[12px] text-accent hover:underline">
          {String(v).slice(0, 12)}…
        </Link>
      );
    case "account":
    case "name":
      return row.account_id ? (
        <Link href={`/app/crm/${String(row.account_id)}`} className="hover:text-accent hover:underline">
          {String(v)}
        </Link>
      ) : (
        <>{String(v)}</>
      );
    case "state":
      return <JobStateBadge state={v as JobState} />;
    case "revenue":
    case "margin":
      return <>{f.money(String(v), currency)}</>;
    case "due_at":
    case "delivered_at":
      return <Time iso={String(v)} mode="relative" />;
    case "hours_overdue":
      return <span className="text-danger">{Number(v) >= 48 ? t("app.dashboardView.days", { count: Math.round(Number(v) / 24) }) : t("app.dashboardView.hours", { count: Number(v) })}</span>;
    case "kind":
      return <Badge>{t.enumLabel(String(v))}</Badge>;
    case "overdue":
      return v ? <Badge tone="danger">{t("app.dashboardView.overdue")}</Badge> : null;
    case "words":
    case "jobs":
      return <>{f.num(Number(v))}</>;
    default:
      return <span className="line-clamp-2">{String(v)}</span>;
  }
}

// ---------------------------------------------------------------- editor

function DashboardEditor({ dashboard, onDone }: { dashboard: Dashboard; onDone: () => void }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [widgets, setWidgets] = useState<Widget[]>(dashboard.widgets);
  const [type, setType] = useState<WidgetType>("kpi");
  const [metric, setMetric] = useState(METRICS.kpi[0]);
  const [size, setSize] = useState<WidgetSize>("s");
  const [busy, setBusy] = useState(false);

  const move = (i: number, d: -1 | 1) =>
    setWidgets((ws) => {
      const j = i + d;
      if (j < 0 || j >= ws.length) return ws;
      const next = [...ws];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  async function save() {
    setBusy(true);
    try {
      await api.updateDashboard(dashboard.id, { widgets: widgets.map(({ id, type: t, metric: m, title, size: sz }) => ({ id, type: t, metric: m, title: title ?? null, size: sz ?? "m" })) });
      toast.success(t("app.dashboardView.dashboardSaved"));
      onDone();
      router.refresh();
    } catch (e) {
      toast.error(t("app.dashboardView.couldNotSave"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <Card>
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold">{t("app.dashboardView.widgets", { count: widgets.length })}</h2>
          <span className="text-[12.5px] text-muted">{t("app.dashboardView.topToBottomLeftTo")}</span>
        </div>
        {widgets.length === 0 ? (
          <EmptyState title={t("app.dashboardView.noWidgetsYet")} description={t("app.dashboardView.addOneFromTheCatalogue")} />
        ) : (
          <ol className="divide-y divide-border">
            {widgets.map((w, i) => (
              <li key={w.id} className="flex items-center gap-3 px-4 py-2">
                <span className="tabular w-5 text-[12px] text-faint">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium">{w.title || metricLabel(t, w.metric)}</div>
                  <div className="text-[12px] text-muted">
                    {widgetTypeLabel(t, w.type)} · {metricLabel(t, w.metric)}
                  </div>
                </div>
                <Select
                  aria-label={t("app.dashboardView.sizeOf", { metric: w.metric })}
                  value={w.size ?? "m"}
                  onChange={(e) => setWidgets((ws) => ws.map((x) => (x.id === w.id ? { ...x, size: e.target.value as WidgetSize } : x)))}
                  className="w-28"
                >
                  <option value="s">{t("app.dashboardView.small")}</option>
                  <option value="m">{t("app.dashboardView.half")}</option>
                  <option value="l">{t("app.dashboardView.fullWidth")}</option>
                </Select>
                <Button size="sm" variant="ghost" aria-label={t("app.dashboardView.moveUp")} disabled={i === 0} onClick={() => move(i, -1)}>
                  <Icons.up className="size-3.5" />
                </Button>
                <Button size="sm" variant="ghost" aria-label={t("app.dashboardView.moveDown")} disabled={i === widgets.length - 1} onClick={() => move(i, 1)}>
                  <Icons.down className="size-3.5" />
                </Button>
                <Button size="sm" variant="ghost" aria-label={t("app.dashboardView.remove", { metric: w.metric })} onClick={() => setWidgets((ws) => ws.filter((x) => x.id !== w.id))}>
                  <Icons.trash className="size-3.5" />
                </Button>
              </li>
            ))}
          </ol>
        )}
        <div className="flex justify-end gap-2 border-t border-border bg-subtle/40 px-4 py-3">
          <Button variant="ghost" onClick={onDone}>
            {t("app.dashboardView.cancel")}
          </Button>
          <Button variant="primary" onClick={save} loading={busy}>
            {t("app.dashboardView.saveDashboard")}
          </Button>
        </div>
      </Card>
      <Card className="self-start p-4">
        <h2 className="text-sm font-semibold">{t("app.dashboardView.addAWidget")}</h2>
        <div className="mt-3 space-y-3">
          <label className="block text-[13px] font-medium">
            {t("app.dashboardView.type")}
            <Select
              className="mt-1"
              value={type}
              onChange={(e) => {
                const nextType = e.target.value as WidgetType;
                setType(nextType);
                setMetric(METRICS[nextType][0]);
                setSize(nextType === "kpi" ? "s" : nextType === "table" || nextType === "line" ? "l" : "m");
              }}
            >
              {(Object.keys(METRICS) as WidgetType[]).map((item) => (
                <option key={item} value={item}>
                  {widgetTypeLabel(t, item)}
                </option>
              ))}
            </Select>
          </label>
          <label className="block text-[13px] font-medium">
            {t("app.dashboardView.metric")}
            <Select className="mt-1" value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS[type].map((m) => (
                <option key={m} value={m}>
                  {metricLabel(t, m)}
                </option>
              ))}
            </Select>
          </label>
          <label className="block text-[13px] font-medium">
            {t("app.dashboardView.size")}
            <Select className="mt-1" value={size} onChange={(e) => setSize(e.target.value as WidgetSize)}>
              <option value="s">{t("app.dashboardView.small")}</option>
              <option value="m">{t("app.dashboardView.half")}</option>
              <option value="l">{t("app.dashboardView.fullWidth")}</option>
            </Select>
          </label>
          <Button
            className="w-full"
            onClick={() => setWidgets((ws) => [...ws, { id: `new-${Date.now().toString(36)}`, type, metric, size, title: metricLabel(t, metric) }])}
          >
            <Icons.plus className="size-3.5" /> {t("app.dashboardView.addWidget")}
          </Button>
        </div>
      </Card>
    </div>
  );
}
