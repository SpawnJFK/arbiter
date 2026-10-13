import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.purchaseOrders.purchaseOrders") };
}

export default async function PurchaseOrdersPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { f, t } = await getI18n();
  const sp = await searchParams;
  const status = ["issued", "invoiced", "cancelled"].includes(sp.status ?? "") ? sp.status : undefined;
  const pos = await withAuth((api) => api.purchaseOrders({ status, limit: 200 }), "/app/purchase-orders");
  return (
    <>
      <PageHeader title={t("app.purchaseOrders.purchaseOrders")} description={t("app.purchaseOrders.description")} />
      <nav aria-label={t("app.purchaseOrders.filter")} className="mb-3 flex flex-wrap gap-1 text-[13px]">
        {[undefined, "issued", "invoiced", "cancelled"].map((s) => (
          <Link
            key={s ?? "all"}
            href={s ? `/app/purchase-orders?status=${s}` : "/app/purchase-orders"}
            aria-current={status === s ? "page" : undefined}
            className={
              status === s
                ? "rounded-md bg-hover px-2.5 py-1 font-medium text-fg"
                : "rounded-md px-2.5 py-1 text-muted hover:text-fg"
            }
          >
            {s ? t.enumLabel(s) : t("app.purchaseOrders.all")}
          </Link>
        ))}
      </nav>
      <Card>
        {pos.items.length === 0 ? (
          <EmptyState title={t("app.purchaseOrders.none")} description={t("app.purchaseOrders.noneHint")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.purchaseOrders.number")}</Th>
                <Th>{t("app.purchaseOrders.vendor")}</Th>
                <Th className="hidden md:table-cell">{t("app.purchaseOrders.job")}</Th>
                <Th>{t("app.purchaseOrders.status")}</Th>
                <Th className="text-right">{t("app.purchaseOrders.total")}</Th>
                <Th className="hidden lg:table-cell">{t("app.purchaseOrders.issued")}</Th>
                <Th className="hidden lg:table-cell">{t("app.purchaseOrders.due")}</Th>
                <Th />
              </tr>
            </THead>
            <TBody>
              {pos.items.map((po) => (
                <Tr key={po.id}>
                  <Td className="font-mono text-[12.5px] font-medium">{po.number}</Td>
                  <Td>
                    <Link href={`/app/vendors/${po.vendor_id}`} className="hover:text-accent hover:underline">
                      {po.vendor_name}
                    </Link>
                  </Td>
                  <Td className="hidden md:table-cell">
                    <Link href={`/app/jobs/${po.job_id}`} className="font-mono text-[12.5px] text-muted hover:text-accent hover:underline">
                      {po.job_id}
                    </Link>
                  </Td>
                  <Td>
                    <Badge tone={po.status === "issued" ? "accent" : po.status === "invoiced" ? "ok" : "neutral"}>{t.enumLabel(po.status)}</Badge>
                  </Td>
                  <Td className="tabular text-right">{f.money(po.total, po.currency)}</Td>
                  <Td className="hidden text-muted lg:table-cell">{f.dateOnly(po.issued_at)}</Td>
                  <Td className="hidden text-muted lg:table-cell">{po.due_at ? f.dateOnly(po.due_at) : "–"}</Td>
                  <Td className="text-right">
                    <a href={`/api/proxy/purchase-orders/${encodeURIComponent(po.id)}/pdf`} className="text-[13px] font-medium text-accent hover:underline" download>
                      {t("app.purchaseOrders.pdf")}
                    </a>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
