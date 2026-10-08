import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { withAuth } from "@/lib/server-api";
import { TIERS } from "@/lib/types";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.priceLists.priceLists") };
}

export default async function PriceListsPage() {
  const { f, t } = await getI18n();
  const [lists, accounts] = await withAuth((api) => Promise.all([api.priceLists({ limit: 200 }), api.accounts({ limit: 200 })]), "/app/price-lists");
  const usage = (id: string) => accounts.items.filter((a) => a.price_list_id === id).length;
  return (
    <>
      <PageHeader
        title={t("app.priceLists.priceLists")}
        description={t("app.priceLists.perWordRatesByTier")}
        actions={
          <ButtonLink href="/app/price-lists/new" variant="primary">
            <Icons.plus className="size-4" /> {t("app.priceLists.newPriceList")}
          </ButtonLink>
        }
      />
      <Card>
        {lists.items.length === 0 ? (
          <EmptyState title={t("app.priceLists.noPriceLists")} description={t("app.priceLists.withoutOneQuotesUseThe")} action={<ButtonLink href="/app/price-lists/new">{t("app.priceLists.createAPriceList")}</ButtonLink>} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.priceLists.name")}</Th>
                {TIERS.map((tier) => (
                  <Th key={tier} className="hidden text-right md:table-cell">
                    {t(`tier.${tier}.label`)}
                  </Th>
                ))}
                <Th className="text-right">{t("app.priceLists.minimum")}</Th>
                <Th className="hidden text-right sm:table-cell">{t("app.priceLists.accounts")}</Th>
                <Th className="hidden lg:table-cell">{t("app.priceLists.updated")}</Th>
              </tr>
            </THead>
            <TBody>
              {lists.items.map((p) => (
                <Tr key={p.id}>
                  <Td>
                    <Link href={`/app/price-lists/${p.id}`} className="font-medium hover:text-accent hover:underline">
                      {p.name}
                    </Link>
                    <div className="text-[12px] text-faint">
                      {t("app.priceLists.rateCount", { count: p.rates.length, currency: p.currency })}
                    </div>
                  </Td>
                  {TIERS.map((tier) => {
                    const r = p.rates.find((x) => x.tier === tier && !x.source_lang && !x.target_lang);
                    return (
                      <Td key={tier} className="tabular hidden text-right md:table-cell">
                        {r ? f.num(Number(r.per_word), 3) : <span className="text-faint">–</span>}
                      </Td>
                    );
                  })}
                  <Td className="tabular text-right">{p.minimum_charge ? f.money(p.minimum_charge, p.currency) : "–"}</Td>
                  <Td className="tabular hidden text-right sm:table-cell">{usage(p.id)}</Td>
                  <Td className="hidden text-muted lg:table-cell">
                    <Time iso={p.updated_at} mode="relative" />
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
