"use client";

import { useI18n } from "@/lib/i18n/client";
// Small dependency-free SVG charts. Values are plain numbers; formatting is passed in.
import { cn } from "@/lib/cn";

export interface Point {
  label: string;
  value: number | null;
}


function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function shortLabel(l: string): string {
  // 2026-07 -> Jul
  const m = /^(\d{4})-(\d{2})$/.exec(l);
  if (m) return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1)).toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
  return l.length > 12 ? `${l.slice(0, 11)}…` : l;
}

export function BarChart({ points, format, height = 180, width = 600, className }: { points: Point[]; format: (n: number) => string; height?: number; width?: number; className?: string }) {
  const { t } = useI18n();
  const W = width;
  const max = niceMax(Math.max(0, ...points.map((p) => p.value ?? 0)));
  const padL = 44;
  const padB = 24;
  const innerW = W - padL - 8;
  const innerH = height - padB - 8;
  const bw = innerW / Math.max(1, points.length);
  const ticks = [0, 0.5, 1].map((frac) => frac * max);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("h-auto w-full", className)} role="img" aria-label={points.map((p) => `${p.label}: ${p.value === null ? "no data" : format(p.value)}`).join(", ")}>
      {ticks.map((tick) => {
        const y = 8 + innerH - (tick / max) * innerH;
        return (
          <g key={tick}>
            <line x1={padL} x2={W - 8} y1={y} y2={y} stroke="var(--border)" strokeDasharray={tick === 0 ? undefined : "3 3"} />
            <text x={padL - 6} y={y + 3.5} textAnchor="end" fontSize="10" fill="var(--faint)">
              {format(tick)}
            </text>
          </g>
        );
      })}
      {points.map((p, i) => {
        const h = ((p.value ?? 0) / max) * innerH;
        const x = padL + i * bw + bw * 0.18;
        return (
          <g key={`${p.label}-${i}`}>
            <rect x={x} y={8 + innerH - h} width={bw * 0.64} height={Math.max(h, p.value ? 1 : 0)} rx="3" fill="var(--accent)" opacity="0.85">
              <title>{t("components.charts.text", { label: p.label, value: p.value === null ? "no data" : format(p.value) })}</title>
            </rect>
            <text x={x + bw * 0.32} y={height - 8} textAnchor="middle" fontSize="10" fill="var(--muted)">
              {shortLabel(p.label)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function LineChart({ points, format, height = 180, width = 600, className }: { points: Point[]; format: (n: number) => string; height?: number; width?: number; className?: string }) {
  const { t } = useI18n();
  const W = width;
  const max = niceMax(Math.max(0, ...points.map((p) => p.value ?? 0)));
  const padL = 44;
  const padB = 24;
  const innerW = W - padL - 16;
  const innerH = height - padB - 12;
  const step = innerW / Math.max(1, points.length - 1);
  const xy = points.map((p, i) => [padL + 8 + i * step, 12 + innerH - ((p.value ?? 0) / max) * innerH] as const);
  const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = xy.length ? `${line} L${xy[xy.length - 1][0].toFixed(1)},${12 + innerH} L${xy[0][0].toFixed(1)},${12 + innerH} Z` : "";
  const ticks = [0, 0.5, 1].map((frac) => frac * max);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className={cn("h-auto w-full", className)} role="img" aria-label={points.map((p) => `${p.label}: ${p.value === null ? "no data" : format(p.value)}`).join(", ")}>
      {ticks.map((tick) => {
        const y = 12 + innerH - (tick / max) * innerH;
        return (
          <g key={tick}>
            <line x1={padL} x2={W - 8} y1={y} y2={y} stroke="var(--border)" strokeDasharray={tick === 0 ? undefined : "3 3"} />
            <text x={padL - 6} y={y + 3.5} textAnchor="end" fontSize="10" fill="var(--faint)">
              {format(tick)}
            </text>
          </g>
        );
      })}
      {area && <path d={area} fill="var(--accent)" opacity="0.08" />}
      {line && <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />}
      {xy.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="3" fill="var(--surface)" stroke="var(--accent)" strokeWidth="2">
            <title>{t("components.charts.text", { label: points[i].label, value: points[i].value === null ? "no data" : format(points[i].value!) })}</title>
          </circle>
          {(points.length <= 13 || i % Math.ceil(points.length / 12) === 0) && (
            <text x={x} y={height - 8} textAnchor="middle" fontSize="10" fill="var(--muted)">
              {shortLabel(points[i].label)}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

/** Tiny inline sparkline-free delta, e.g. "+12% vs previous period". */
export function Delta({ value, previous, invert = false }: { value: number | null; previous: number | null; invert?: boolean }) {
  if (value === null || previous === null || previous === 0) return null;
  const d = (value - previous) / Math.abs(previous);
  const good = invert ? d < 0 : d > 0;
  return (
    <span className={cn("tabular text-[12px] font-medium", Math.abs(d) < 0.005 ? "text-faint" : good ? "text-ok" : "text-danger")}>
      {d > 0 ? "+" : ""}
      {(d * 100).toFixed(0)}%
    </span>
  );
}
