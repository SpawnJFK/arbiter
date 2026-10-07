import { AppShell, type NavSection } from "@/components/shell";
import { getMe } from "@/lib/server-api";

const sections: NavSection[] = [
  {
    label: "Community",
    items: [
      { href: "/admin", label: "Reviewers", icon: "users", exact: true },
      { href: "/admin/disputes", label: "Disputes", icon: "scale" },
      { href: "/admin/payouts", label: "Payouts", icon: "wallet" },
    ],
  },
  { label: "Customers", items: [{ href: "/admin/orgs", label: "Organisations", icon: "building" }] },
];

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user } = await getMe();
  return (
    <AppShell sections={sections} user={user} context="Operator">
      {children}
    </AppShell>
  );
}
