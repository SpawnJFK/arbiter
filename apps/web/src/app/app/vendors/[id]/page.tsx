import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { VendorProfile } from "./vendor-profile";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.vendors.detail.vendor") };
}

export default async function VendorPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const vendor = await withAuth((api) => api.vendor(id), `/app/vendors/${id}`);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/vendors" className="hover:text-fg">
            {t("app.vendors.vendors")}
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-2">
            {vendor.name}
            <Badge tone={vendor.status === "active" ? "ok" : vendor.status === "blocked" ? "danger" : "neutral"}>
              {t.enumLabel(vendor.status)}
            </Badge>
          </span>
        }
        description={[t.enumLabel(vendor.kind), vendor.email, vendor.country].filter(Boolean).join(" · ")}
      />
      <VendorProfile vendor={vendor} />
    </>
  );
}
