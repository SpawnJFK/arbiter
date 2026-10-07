import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { PriceListEditor } from "./editor";

export const metadata: Metadata = { title: "Price list" };

export default async function PriceListPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const pl = id === "new" ? null : await withAuth((api) => api.priceList(id), `/app/price-lists/${id}`);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/price-lists" className="hover:text-fg">
            Price lists
          </Link>
        }
        title={pl ? pl.name : "New price list"}
      />
      <PriceListEditor priceList={pl} />
    </>
  );
}
