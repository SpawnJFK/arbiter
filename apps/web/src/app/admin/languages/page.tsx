import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { SOURCE_LOCALE } from "@/lib/i18n/core";
import { getI18n, SOURCE_MESSAGES } from "@/lib/i18n/server";
import { withAuth } from "@/lib/server-api";
import { LanguagesManager, type LanguageRow } from "./languages-manager";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("admin.languages.title") };
}

export default async function LanguagesPage() {
  const { t } = await getI18n();
  const total = Object.keys(SOURCE_MESSAGES).length;
  const rows = await withAuth(async (api) => {
    const { items } = await api.i18nLocales();
    return Promise.all(
      items.map(async (l): Promise<LanguageRow> => {
        if (l.locale === SOURCE_LOCALE) return { ...l, message_count: total, translated: total };
        // Coverage counts only keys the English catalog still has.
        const { messages } = await api.i18nMessages(l.locale).catch(() => ({ messages: {} as Record<string, string> }));
        const translated = Object.keys(messages).filter((k) => k in SOURCE_MESSAGES).length;
        return { ...l, translated };
      }),
    );
  }, "/admin/languages");
  return (
    <>
      <PageHeader title={t("admin.languages.title")} description={t("admin.languages.description", { total })} />
      <LanguagesManager rows={rows} total={total} />
    </>
  );
}
