import { getI18n } from "@/lib/i18n/server";
import { SubNav } from "@/components/sub-nav";
import { PageHeader } from "@/components/ui/misc";

export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  return (
    <>
      <PageHeader title={t("app.settings.layout.settings")} />
      <SubNav
        label={t("app.settings.layout.settings")}
        items={[
          { href: "/app/settings", label: t("app.settings.layout.policies") },
          { href: "/app/settings/api-keys", label: t("app.settings.layout.apiKeys") },
          { href: "/app/settings/webhooks", label: t("app.settings.layout.webhooks") },
          { href: "/app/settings/billing", label: t("app.settings.layout.usageInvoices") },
        ]}
      />
      {children}
    </>
  );
}
