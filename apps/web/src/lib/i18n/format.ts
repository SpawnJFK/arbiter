// Locale-aware formatters (Intl). Times are shown in UTC so server and client render the same text.
export interface Formatters {
  locale: string;
  money: (amount: string | number | null | undefined, currency?: string) => string;
  pct: (v: number | null | undefined, digits?: number) => string;
  /** Grouped number; `digits` fixes the fraction digits (e.g. per-word rates). */
  num: (v: number | null | undefined, digits?: number) => string;
  score: (v: number | null | undefined) => string;
  dateTime: (iso: string | null | undefined) => string;
  dateOnly: (iso: string | null | undefined) => string;
  relative: (iso: string | null | undefined, now?: number) => string;
  hours: (h: number | null | undefined) => string;
  langName: (code: string) => string;
  month: (yyyyMm: string) => string;
}

const cache = new Map<string, Formatters>();

/** Intl wants a real locale; fall back to en for anything it rejects. */
function safe(locale: string): string {
  try {
    return Intl.getCanonicalLocales(locale)[0] ?? "en";
  } catch {
    return "en";
  }
}

export function makeFormat(localeIn: string): Formatters {
  const hit = cache.get(localeIn);
  if (hit) return hit;
  const locale = safe(localeIn);
  // English UI uses British-style dates (07 Oct 2026); other locales use their own conventions.
  const dl = locale === "en" ? "en-GB" : locale;
  const nf = new Intl.NumberFormat(locale);
  const dtf = new Intl.DateTimeFormat(dl, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  const df = new Intl.DateTimeFormat(dl, { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const unitFmt = (unit: "minute" | "hour" | "day", n: number) => new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: 0 }).format(n);
  let names: Intl.DisplayNames | null = null;
  const f: Formatters = {
    locale,
    money(amount, currency = "EUR") {
      if (amount === null || amount === undefined || amount === "") return "–";
      const n = typeof amount === "number" ? amount : Number(amount);
      if (!Number.isFinite(n)) return String(amount);
      try {
        return new Intl.NumberFormat(locale, { style: "currency", currency, minimumFractionDigits: 2 }).format(n);
      } catch {
        return `${nf.format(n)} ${currency}`;
      }
    },
    pct(v, digits = 0) {
      if (v === null || v === undefined || !Number.isFinite(v)) return "–";
      return new Intl.NumberFormat(locale, { style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
    },
    num(v, digits) {
      if (v === null || v === undefined) return "–";
      return digits === undefined ? nf.format(v) : new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
    },
    score(v) {
      if (v === null || v === undefined) return "–";
      const x = v <= 1 ? v * 100 : v;
      return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(x);
    },
    dateTime(iso) {
      if (!iso) return "–";
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? iso : `${dtf.format(d)} UTC`;
    },
    dateOnly(iso) {
      if (!iso) return "–";
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? iso : df.format(d);
    },
    relative(iso, now = Date.now()) {
      if (!iso) return "–";
      const diff = new Date(iso).getTime() - now;
      const abs = Math.abs(diff);
      const units: [Intl.RelativeTimeFormatUnit, number][] = [
        ["day", 86_400_000],
        ["hour", 3_600_000],
        ["minute", 60_000],
      ];
      for (const [unit, ms] of units) if (abs >= ms) return rtf.format(Math.round(diff / ms), unit);
      return rtf.format(0, "minute");
    },
    hours(h) {
      if (h === null || h === undefined) return "–";
      if (h < 1) return unitFmt("minute", Math.max(1, Math.round(h * 60)));
      if (h < 48) return unitFmt("hour", Math.round(h));
      return unitFmt("day", Math.round(h / 24));
    },
    langName(code) {
      try {
        names ??= new Intl.DisplayNames([locale], { type: "language" });
        return names.of(code) ?? code;
      } catch {
        return code;
      }
    },
    month(yyyyMm) {
      const m = /^(\d{4})-(\d{2})$/.exec(yyyyMm);
      if (!m) return yyyyMm;
      return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1)).toLocaleString(dl, { month: "short", timeZone: "UTC" });
    },
  };
  cache.set(localeIn, f);
  return f;
}
