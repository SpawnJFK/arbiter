import "server-only";
import { cookies, headers } from "next/headers";
import { cache } from "react";
import en from "../../../messages/en.json";
import { backendFetch } from "../backend";
import { createTranslator, LOCALE_COOKIE, SOURCE_LOCALE, type Messages, type Translator } from "./core";
import { makeFormat, type Formatters } from "./format";
import { resolveLocale, type LocaleInfo } from "./locales";

export const SOURCE_MESSAGES = en as Messages;

const TTL = 60_000;
type Entry<T> = { at: number; value: T };
type Store = { locales?: Entry<LocaleInfo[]>; messages: Map<string, Entry<Messages>> };
const g = globalThis as unknown as { __arbiterI18n?: Store };
const store: Store = (g.__arbiterI18n ??= { messages: new Map<string, Entry<Messages>>() });

const FALLBACK: LocaleInfo[] = [{ locale: SOURCE_LOCALE, name: "English", enabled: true, message_count: null, updated_at: null }];

/** Enabled locales from the backend (public endpoint), cached for 60 s. English is always first. */
export async function enabledLocales(): Promise<LocaleInfo[]> {
  const hit = store.locales;
  if (hit && Date.now() - hit.at < TTL) return hit.value;
  let value = FALLBACK;
  try {
    const res = await backendFetch("/i18n/locales", { headers: { Accept: "application/json" } });
    if (res.ok) {
      const items = ((await res.json()) as { items?: LocaleInfo[] }).items ?? [];
      const enabled = items.filter((l) => l.enabled);
      value = enabled.some((l) => l.locale === SOURCE_LOCALE) ? enabled : [...FALLBACK, ...enabled];
    }
  } catch {
    value = FALLBACK;
  }
  store.locales = { at: Date.now(), value };
  return value;
}

/** Backend overrides for a locale ({} for English or on error), cached for 60 s. */
export async function localeMessages(locale: string): Promise<Messages> {
  if (locale === SOURCE_LOCALE) return {};
  const hit = store.messages.get(locale);
  if (hit && Date.now() - hit.at < TTL) return hit.value;
  let value: Messages = {};
  try {
    const res = await backendFetch(`/i18n/messages/${encodeURIComponent(locale)}`, { headers: { Accept: "application/json" } });
    if (res.ok) value = ((await res.json()) as { messages?: Messages }).messages ?? {};
  } catch {
    value = {};
  }
  store.messages.set(locale, { at: Date.now(), value });
  return value;
}

/** Drop cached locales/messages (after an admin import or locale change on this server). */
export function invalidateI18nCache(locale?: string) {
  store.locales = undefined;
  if (locale) store.messages.delete(locale);
  else store.messages.clear();
}

export interface I18n {
  locale: string;
  locales: LocaleInfo[];
  /** Active overrides only (English comes from the bundled catalog). */
  overrides: Messages;
  t: Translator;
  f: Formatters;
}

/** Per-request translator for Server Components and route handlers. */
export const getI18n = cache(async (): Promise<I18n> => {
  const [jar, hdrs, locales] = await Promise.all([cookies(), headers(), enabledLocales()]);
  const locale = resolveLocale(jar.get(LOCALE_COOKIE)?.value, hdrs.get("accept-language"), locales.map((l) => l.locale));
  const overrides = await localeMessages(locale);
  return { locale, locales, overrides, t: createTranslator(locale, SOURCE_MESSAGES, overrides), f: makeFormat(locale) };
});
