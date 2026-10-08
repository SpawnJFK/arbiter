"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import en from "../../../messages/en.json";
import { createTranslator, type Messages, type Translator } from "./core";
import { makeFormat, type Formatters } from "./format";
import type { LocaleInfo } from "./locales";

interface Ctx {
  locale: string;
  locales: LocaleInfo[];
  t: Translator;
  f: Formatters;
}

const I18nContext = createContext<Ctx | null>(null);

/** English ships in the bundle; only the active locale's overrides cross the wire. */
export function I18nProvider({ locale, locales, overrides, children }: { locale: string; locales: LocaleInfo[]; overrides: Messages; children: ReactNode }) {
  const value = useMemo<Ctx>(
    () => ({ locale, locales, t: createTranslator(locale, en as Messages, overrides), f: makeFormat(locale) }),
    [locale, locales, overrides],
  );
  return <I18nContext value={value}>{children}</I18nContext>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}
