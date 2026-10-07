import { SubNav } from "@/components/sub-nav";
import { PageHeader } from "@/components/ui/misc";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Settings" />
      <SubNav
        label="Settings"
        items={[
          { href: "/app/settings", label: "Policies" },
          { href: "/app/settings/api-keys", label: "API keys" },
          { href: "/app/settings/webhooks", label: "Webhooks" },
          { href: "/app/settings/billing", label: "Usage & invoices" },
        ]}
      />
      {children}
    </>
  );
}
