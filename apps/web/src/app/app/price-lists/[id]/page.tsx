import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { PriceListEditor } from "./editor";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.priceLists.detail.priceList") };
}

export default async function PriceListPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const pl = id === "new" ? null : await withAuth((api) => api.priceList(id), `/app/price-lists/${id}`);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/price-lists" className="hover:text-fg">
            {t("app.priceLists.detail.priceLists")}
          </Link>
        }
        title={pl ? pl.name : t("app.priceLists.detail.newPriceList")}
      />
      <PriceListEditor priceList={pl} />
    </>
  );
}
