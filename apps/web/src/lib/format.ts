// Deterministic formatting (fixed locale, UTC) so server and client render the same text.

const LOCALE = "en-GB";

export function money(amount: string | number | null | undefined, currency = "EUR"): string {
  if (amount === null || amount === undefined || amount === "") return "–";
  const n = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(n)) return String(amount);
  return new Intl.NumberFormat(LOCALE, { style: "currency", currency, minimumFractionDigits: 2 }).format(n);
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return new Intl.NumberFormat(LOCALE).format(v);
}

/** QE scores are 0-100 (backend D-005); one decimal unless whole. */
export function score(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  const x = v <= 1 ? v * 100 : v;
  return Number.isInteger(x) ? String(x) : x.toFixed(1);
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(d)} UTC`;
}

export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
}

export function relative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "–";
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];
  for (const [unit, ms] of units) {
    if (abs >= ms) return rtf.format(Math.round(diff / ms), unit);
  }
  return "just now";
}

export function hours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "–";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} days`;
}

let displayNames: Intl.DisplayNames | null = null;
export function langName(code: string): string {
  try {
    displayNames ??= new Intl.DisplayNames(["en"], { type: "language" });
    return displayNames.of(code) ?? code;
  } catch {
    return code;
  }
}

export function pair(src: string, tgt: string): string {
  return `${src} → ${tgt}`;
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "–";
  const item = s.replace(/_/g, " ");
  return item.charAt(0).toUpperCase() + item.slice(1);
}

/** True when the ISO time is in the past (evaluated now; relative-time UI tolerates drift). */
export function isPast(iso: string | null | undefined): boolean {
  return Boolean(iso) && new Date(iso as string).getTime() < Date.now();
}
