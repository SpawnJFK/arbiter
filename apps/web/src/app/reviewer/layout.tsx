import { AppShell, type NavSection } from "@/components/shell";
import { getI18n } from "@/lib/i18n/server";
import { getMe } from "@/lib/server-api";

export default async function ReviewerLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  const { user } = await getMe();
  const sections: NavSection[] = [
    {
      items: [
        { href: "/reviewer", label: t("reviewer.layout.dashboard"), icon: "home", exact: true },
        { href: "/reviewer/cockpit", label: t("reviewer.layout.reviewCockpit"), icon: "target" },
        { href: "/reviewer/tests", label: t("reviewer.layout.tests"), icon: "check" },
      ],
    },
    {
      label: t("reviewer.layout.account"),
      items: [
        { href: "/reviewer/earnings", label: t("reviewer.layout.earningsPayouts"), icon: "wallet" },
        { href: "/reviewer/disputes", label: t("reviewer.layout.disputes"), icon: "flag" },
      ],
    },
  ];
  return (
    <AppShell sections={sections} user={user} context={t("reviewer.layout.context")}>
      {children}
    </AppShell>
  );
}
