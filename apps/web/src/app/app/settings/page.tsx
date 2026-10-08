import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { getMe, withAuth } from "@/lib/server-api";
import { PolicyForm } from "./policy-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.settings.metaTitle") };
}

export default async function PoliciesPage() {
  const [{ user }, org] = await Promise.all([getMe(), withAuth((api) => api.org(), "/app/settings")]);
  return <PolicyForm org={org} canEdit={user.role === "pm"} />;
}
