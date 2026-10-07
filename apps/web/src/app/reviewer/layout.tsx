import { AppShell, type NavSection } from "@/components/shell";
import { getMe } from "@/lib/server-api";

const sections: NavSection[] = [
  {
    items: [
      { href: "/reviewer", label: "Dashboard", icon: "home", exact: true },
      { href: "/reviewer/cockpit", label: "Review cockpit", icon: "target" },
      { href: "/reviewer/tests", label: "Tests", icon: "check" },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/reviewer/earnings", label: "Earnings & payouts", icon: "wallet" },
      { href: "/reviewer/disputes", label: "Disputes", icon: "flag" },
    ],
  },
];

export default async function ReviewerLayout({ children }: { children: React.ReactNode }) {
  const { user } = await getMe();
  return (
    <AppShell sections={sections} user={user} context="Reviewer">
      {children}
    </AppShell>
  );
}
