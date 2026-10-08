import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { ApiKeys } from "./api-keys";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.settings.apiKeys.metaTitle") };
}

export default async function ApiKeysPage() {
  const { items } = await withAuth((api) => api.apiKeys(), "/app/settings/api-keys");
  return <ApiKeys initial={items} />;
}
