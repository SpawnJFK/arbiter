import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { SsoSettings } from "./sso-settings";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("platform.sso.metaTitle") };
}

export default async function SsoPage() {
  const [config, roles] = await withAuth((api) => Promise.all([api.sso(), api.roles()]), "/app/settings/sso");
  return <SsoSettings initial={config} roles={roles.items} />;
}
