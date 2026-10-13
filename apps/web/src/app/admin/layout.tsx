import { AppShell, type NavSection } from "@/components/shell";
import { getI18n } from "@/lib/i18n/server";
import { getMe } from "@/lib/server-api";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  const { user } = await getMe();
  const sections: NavSection[] = [
    {
      label: t("admin.layout.community"),
      items: [
        { href: "/admin", label: t("admin.layout.reviewers"), icon: "users", exact: true },
        { href: "/admin/disputes", label: t("admin.layout.disputes"), icon: "scale" },
        { href: "/admin/payouts", label: t("admin.layout.payouts"), icon: "wallet" },
      ],
    },
    {
      label: t("admin.layout.customers"),
      items: [
        { href: "/admin/orgs", label: t("admin.layout.organisations"), icon: "building" },
        { href: "/admin/billing", label: t("admin.layout.billing"), icon: "receipt" },
      ],
    },
    {
      label: t("admin.layout.platform"),
      items: [
        { href: "/admin/languages", label: t("admin.layout.languages"), icon: "globe" },
        { href: "/admin/engines", label: t("admin.layout.engines"), icon: "key" },
      ],
    },
  ];
  return (
    <AppShell sections={sections} user={user} context={t("admin.layout.context")}>
      {children}
    </AppShell>
  );
}
