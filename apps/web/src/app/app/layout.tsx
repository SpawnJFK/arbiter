import { AppShell, type NavSection } from "@/components/shell";
import { getMe } from "@/lib/server-api";

export default async function CustomerLayout({ children }: { children: React.ReactNode }) {
  const { user, org } = await getMe();
  const isPm = user.role === "pm";
  const sections: NavSection[] = isPm
    ? [
        {
          items: [
            { href: "/app", label: "Dashboard", icon: "grid", exact: true },
            { href: "/app/assistant", label: "Assistant", icon: "sparkle" },
          ],
        },
        {
          label: "Production",
          items: [
            { href: "/app/projects", label: "Projects", icon: "folder" },
            { href: "/app/projects/new", label: "New project", icon: "plus" },
            { href: "/app/exceptions", label: "Exceptions", icon: "alert" },
          ],
        },
        {
          label: "Business",
          items: [
            { href: "/app/crm", label: "Accounts", icon: "building" },
            { href: "/app/crm/deals", label: "Deals", icon: "kanban" },
            { href: "/app/crm/tasks", label: "My tasks", icon: "checklist" },
            { href: "/app/price-lists", label: "Price lists", icon: "tag" },
            { href: "/app/workflows", label: "Workflows", icon: "flow" },
          ],
        },
        {
          label: "Language assets",
          items: [
            { href: "/app/glossaries", label: "Glossaries", icon: "book" },
            { href: "/app/tm", label: "Translation memory", icon: "db" },
            { href: "/app/term-questions", label: "Term questions", icon: "question" },
          ],
        },
        {
          label: "Organisation",
          items: [
            { href: "/app/quality", label: "Quality", icon: "chart" },
            { href: "/app/settings", label: "Settings", icon: "gear" },
          ],
        },
      ]
    : [
        {
          items: [
            { href: "/app", label: "Dashboard", icon: "grid", exact: true },
            { href: "/app/projects", label: "Projects", icon: "folder" },
            { href: "/app/projects/new", label: "New project", icon: "plus" },
          ],
        },
        {
          label: "Language assets",
          items: [
            { href: "/app/glossaries", label: "Glossaries", icon: "book" },
            { href: "/app/tm", label: "Translation memory", icon: "db" },
            { href: "/app/term-questions", label: "Term questions", icon: "question" },
          ],
        },
        {
          label: "Organisation",
          items: [
            { href: "/app/quality", label: "Quality", icon: "chart" },
            { href: "/app/settings", label: "Settings", icon: "gear" },
          ],
        },
      ];
  return (
    <AppShell sections={sections} user={user} context={org?.name}>
      {children}
    </AppShell>
  );
}
