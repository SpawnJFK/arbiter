import { getI18n } from "@/lib/i18n/server";
import { SubNav } from "@/components/sub-nav";
import { PageHeader } from "@/components/ui/misc";
import { can } from "@/lib/modules";
import { getMe } from "@/lib/server-api";

export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  const me = await getMe();
  const items = [
    { href: "/app/settings", label: t("app.settings.layout.policies") },
    { href: "/app/settings/api-keys", label: t("app.settings.layout.apiKeys") },
    { href: "/app/settings/webhooks", label: t("app.settings.layout.webhooks") },
    { href: "/app/settings/billing", label: t("app.settings.layout.usageInvoices") },
    { href: "/app/settings/modules", label: t("platform.settings.modules") },
  ];
  if (can(me, "users.read")) items.push({ href: "/app/settings/team", label: t("platform.settings.teamRoles") });
  if (can(me, "audit.read")) items.push({ href: "/app/settings/audit", label: t("platform.settings.auditLog") });
  if (can(me, "org.manage")) items.push({ href: "/app/settings/sso", label: t("platform.settings.sso") });
  return (
    <>
      <PageHeader title={t("app.settings.layout.settings")} />
      <SubNav label={t("app.settings.layout.settings")} items={items} />
      {children}
    </>
  );
}
