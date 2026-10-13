import { getI18n } from "@/lib/i18n/server";
import { Analytics } from "@/components/analytics";
import { AppShell, type NavSection } from "@/components/shell";
import { filterByModule } from "@/lib/modules";
import { getMe } from "@/lib/server-api";

export default async function CustomerLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  const { user, org } = await getMe();
  const isPm = user.role === "pm";
  const all: NavSection[] = isPm
    ? [
        {
          items: [
            { href: "/app", label: t("app.layout.dashboard"), icon: "grid", exact: true, module: "pm" },
            { href: "/app/assistant", label: t("app.layout.assistant"), icon: "sparkle", module: "pm" },
          ],
        },
        {
          label: t("app.layout.production"),
          items: [
            { href: "/app/projects", label: t("app.layout.projects"), icon: "folder", module: "tms" },
            { href: "/app/projects/new", label: t("app.layout.newProject"), icon: "plus", module: "tms" },
            { href: "/app/exceptions", label: t("app.layout.exceptions"), icon: "alert", module: "tms" },
            { href: "/app/strings", label: t("app.layout.strings"), icon: "globe", module: "strings" },
            { href: "/app/queries", label: t("app.layout.queries"), icon: "question", module: "tms" },
            { href: "/app/auditor", label: t("app.layout.auditor"), icon: "checklist", module: "auditor" },
          ],
        },
        {
          label: t("app.layout.business"),
          items: [
            { href: "/app/crm", label: t("app.layout.accounts"), icon: "building", module: "pm" },
            { href: "/app/crm/deals", label: t("app.layout.deals"), icon: "kanban", module: "pm" },
            { href: "/app/crm/tasks", label: t("app.layout.myTasks"), icon: "checklist", module: "pm" },
            { href: "/app/price-lists", label: t("app.layout.priceLists"), icon: "tag", module: "pm" },
            { href: "/app/workflows", label: t("app.layout.workflows"), icon: "flow", module: "pm" },
          ],
        },
        {
          label: t("app.layout.languageAssets"),
          items: [
            { href: "/app/glossaries", label: t("app.layout.glossaries"), icon: "book", module: "tms" },
            { href: "/app/tm", label: t("app.layout.translationMemory"), icon: "db", module: "tms" },
            { href: "/app/term-questions", label: t("app.layout.termQuestions"), icon: "question", module: "tms" },
          ],
        },
        {
          label: t("app.layout.organisation"),
          items: [
            { href: "/app/quality", label: t("app.layout.quality"), icon: "chart", module: "ai" },
            { href: "/app/engines", label: t("app.layout.engines"), icon: "flow", module: "engine" },
            { href: "/app/training", label: t("app.layout.ownModels"), icon: "sparkle", module: "engine" },
            { href: "/app/settings", label: t("app.layout.settings"), icon: "gear" },
          ],
        },
      ]
    : [
        {
          items: [
            { href: "/app", label: t("app.layout.dashboard"), icon: "grid", exact: true, module: "pm" },
            { href: "/app/projects", label: t("app.layout.projects"), icon: "folder", module: "tms" },
            { href: "/app/projects/new", label: t("app.layout.newProject"), icon: "plus", module: "tms" },
            { href: "/app/strings", label: t("app.layout.strings"), icon: "globe", module: "strings" },
            { href: "/app/queries", label: t("app.layout.queries"), icon: "question", module: "tms" },
          ],
        },
        {
          label: t("app.layout.languageAssets"),
          items: [
            { href: "/app/glossaries", label: t("app.layout.glossaries"), icon: "book", module: "tms" },
            { href: "/app/tm", label: t("app.layout.translationMemory"), icon: "db", module: "tms" },
            { href: "/app/term-questions", label: t("app.layout.termQuestions"), icon: "question", module: "tms" },
          ],
        },
        {
          label: t("app.layout.organisation"),
          items: [
            { href: "/app/quality", label: t("app.layout.quality"), icon: "chart", module: "ai" },
            { href: "/app/settings", label: t("app.layout.settings"), icon: "gear" },
          ],
        },
      ];
  // Sections of modules the org has not enabled are hidden; the API answers 404 module_disabled.
  const sections = filterByModule(all, org);
  return (
    <AppShell sections={sections} user={user} context={org?.name}>
      <Analytics userId={user.id} role={user.role} />
      {children}
    </AppShell>
  );
}
