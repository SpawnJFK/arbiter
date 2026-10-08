import { getI18n } from "@/lib/i18n/server";
import { AppShell, type NavSection } from "@/components/shell";
import { getMe } from "@/lib/server-api";

export default async function CustomerLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  const { user, org } = await getMe();
  const isPm = user.role === "pm";
  const sections: NavSection[] = isPm
    ? [
        {
          items: [
            { href: "/app", label: t("app.layout.dashboard"), icon: "grid", exact: true },
            { href: "/app/assistant", label: t("app.layout.assistant"), icon: "sparkle" },
          ],
        },
        {
          label: t("app.layout.production"),
          items: [
            { href: "/app/projects", label: t("app.layout.projects"), icon: "folder" },
            { href: "/app/projects/new", label: t("app.layout.newProject"), icon: "plus" },
            { href: "/app/exceptions", label: t("app.layout.exceptions"), icon: "alert" },
          ],
        },
        {
          label: t("app.layout.business"),
          items: [
            { href: "/app/crm", label: t("app.layout.accounts"), icon: "building" },
            { href: "/app/crm/deals", label: t("app.layout.deals"), icon: "kanban" },
            { href: "/app/crm/tasks", label: t("app.layout.myTasks"), icon: "checklist" },
            { href: "/app/price-lists", label: t("app.layout.priceLists"), icon: "tag" },
            { href: "/app/workflows", label: t("app.layout.workflows"), icon: "flow" },
          ],
        },
        {
          label: t("app.layout.languageAssets"),
          items: [
            { href: "/app/glossaries", label: t("app.layout.glossaries"), icon: "book" },
            { href: "/app/tm", label: t("app.layout.translationMemory"), icon: "db" },
            { href: "/app/term-questions", label: t("app.layout.termQuestions"), icon: "question" },
          ],
        },
        {
          label: t("app.layout.organisation"),
          items: [
            { href: "/app/quality", label: t("app.layout.quality"), icon: "chart" },
            { href: "/app/settings", label: t("app.layout.settings"), icon: "gear" },
          ],
        },
      ]
    : [
        {
          items: [
            { href: "/app", label: t("app.layout.dashboard"), icon: "grid", exact: true },
            { href: "/app/projects", label: t("app.layout.projects"), icon: "folder" },
            { href: "/app/projects/new", label: t("app.layout.newProject"), icon: "plus" },
          ],
        },
        {
          label: t("app.layout.languageAssets"),
          items: [
            { href: "/app/glossaries", label: t("app.layout.glossaries"), icon: "book" },
            { href: "/app/tm", label: t("app.layout.translationMemory"), icon: "db" },
            { href: "/app/term-questions", label: t("app.layout.termQuestions"), icon: "question" },
          ],
        },
        {
          label: t("app.layout.organisation"),
          items: [
            { href: "/app/quality", label: t("app.layout.quality"), icon: "chart" },
            { href: "/app/settings", label: t("app.layout.settings"), icon: "gear" },
          ],
        },
      ];
  return (
    <AppShell sections={sections} user={user} context={org?.name}>
      {children}
    </AppShell>
  );
}
