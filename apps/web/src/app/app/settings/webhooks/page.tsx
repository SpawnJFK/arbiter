import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { Webhooks } from "./webhooks";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.settings.webhooks.metaTitle") };
}

export default async function WebhooksPage() {
  const { items } = await withAuth((api) => api.webhooks(), "/app/settings/webhooks");
  return <Webhooks initial={items} />;
}
