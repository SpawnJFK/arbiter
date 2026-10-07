import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { money, TIER_LABEL } from "@/lib/format";
import { withAuth } from "@/lib/server-api";
import { TIERS } from "@/lib/types";

export const metadata: Metadata = { title: "Price lists" };

export default async function PriceListsPage() {
  const [lists, accounts] = await withAuth((api) => Promise.all([api.priceLists({ limit: 200 }), api.accounts({ limit: 200 })]), "/app/price-lists");
  const usage = (id: string) => accounts.items.filter((a) => a.price_list_id === id).length;
  return (
    <>
      <PageHeader
        title="Price lists"
        description="Per-word rates by tier and language pair. Quotes for an account use its price list: exact pair first, then target language, then tier only, then your org default."
        actions={
          <ButtonLink href="/app/price-lists/new" variant="primary">
            <Icons.plus className="size-4" /> New price list
          </ButtonLink>
        }
      />
      <Card>
        {lists.items.length === 0 ? (
          <EmptyState title="No price lists" description="Without one, quotes use the platform's default rates." action={<ButtonLink href="/app/price-lists/new">Create a price list</ButtonLink>} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                {TIERS.map((t) => (
                  <Th key={t} className="hidden text-right md:table-cell">
                    {TIER_LABEL[t]}
                  </Th>
                ))}
                <Th className="text-right">Minimum</Th>
                <Th className="hidden text-right sm:table-cell">Accounts</Th>
                <Th className="hidden lg:table-cell">Updated</Th>
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
                      {p.rates.length} rate{p.rates.length === 1 ? "" : "s"} · {p.currency}
                    </div>
                  </Td>
                  {TIERS.map((t) => {
                    const r = p.rates.find((x) => x.tier === t && !x.source_lang && !x.target_lang);
                    return (
                      <Td key={t} className="tabular hidden text-right md:table-cell">
                        {r ? `${Number(r.per_word).toFixed(3)}` : <span className="text-faint">–</span>}
                      </Td>
                    );
                  })}
                  <Td className="tabular text-right">{p.minimum_charge ? money(p.minimum_charge, p.currency) : "–"}</Td>
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
