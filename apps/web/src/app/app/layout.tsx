import { AppShell, type NavSection } from "@/components/shell";
import { getMe } from "@/lib/server-api";

export default async function CustomerLayout({ children }: { children: React.ReactNode }) {
  const { user, org } = await getMe();
  const isPm = user.role === "pm";
  const sections: NavSection[] = [
    {
      items: [
        { href: "/app", label: "Projects", icon: "folder", exact: true },
        { href: "/app/projects/new", label: "New project", icon: "plus" },
        ...(isPm ? [{ href: "/app/exceptions", label: "Exceptions", icon: "alert" as const }] : []),
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
