import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { withAuth } from "@/lib/server-api";
import { ImportVendorsButton, NewVendorButton, VendorFilters } from "./vendor-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.vendors.vendors") };
}

export default async function VendorsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; pair?: string }>;
}) {
  const { f, t } = await getI18n();
  const sp = await searchParams;
  const status = sp.status === "inactive" || sp.status === "blocked" ? sp.status : "active";
  const [source_lang, target_lang] = (sp.pair ?? "").includes(">") ? (sp.pair ?? "").split(">") : [undefined, undefined];
  const vendors = await withAuth((api) => api.vendors({ q: sp.q, status, source_lang, target_lang, limit: 200 }), "/app/vendors");
  const filtered = Boolean(sp.q || sp.pair);
  return (
    <>
      <PageHeader
        title={t("app.vendors.vendors")}
        description={t("app.vendors.description")}
        actions={
          <>
            <ImportVendorsButton />
            <NewVendorButton />
          </>
        }
      />
      <VendorFilters q={sp.q ?? ""} status={status} pair={sp.pair ?? ""} />
      <Card>
        {vendors.items.length === 0 ? (
          <EmptyState
            title={filtered ? t("app.vendors.noVendorsMatch") : t("app.vendors.noVendorsYet")}
            description={filtered ? t("app.vendors.tryAnotherSearch") : t("app.vendors.addYourFirstVendor")}
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.vendors.name")}</Th>
                <Th>{t("app.vendors.pairs")}</Th>
                <Th className="hidden md:table-cell">{t("app.vendors.services")}</Th>
                <Th className="hidden text-right lg:table-cell">{t("app.vendors.capacityPerDay")}</Th>
                <Th className="hidden text-right sm:table-cell">{t("app.vendors.openAssignments")}</Th>
                <Th className="hidden lg:table-cell">{t("app.vendors.rating")}</Th>
                <Th className="hidden xl:table-cell">{t("app.vendors.nda")}</Th>
              </tr>
            </THead>
            <TBody>
              {vendors.items.map((v) => {
                const services = Array.from(new Set(v.pairs.flatMap((p) => p.services)));
                return (
                  <Tr key={v.id}>
                    <Td>
                      <Link href={`/app/vendors/${v.id}`} className="font-medium hover:text-accent hover:underline">
                        {v.name}
                      </Link>
                      <div className="text-[12px] text-faint">
                        {t.enumLabel(v.kind)}
                        {v.email ? ` · ${v.email}` : ""}
                      </div>
                    </Td>
                    <Td className="text-[13px]">
                      {v.pairs.length === 0 ? (
                        <span className="text-faint">–</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {v.pairs.slice(0, 4).map((p) => (
                            <Badge key={`${p.source_lang}>${p.target_lang}`}>
                              {p.source_lang} → {p.target_lang}
                            </Badge>
                          ))}
                          {v.pairs.length > 4 && <span className="text-faint">+{v.pairs.length - 4}</span>}
                        </span>
                      )}
                    </Td>
                    <Td className="hidden text-[13px] text-muted md:table-cell">{services.map((s) => t.enumLabel(s)).join(", ") || "–"}</Td>
                    <Td className="tabular hidden text-right lg:table-cell">{f.num(v.capacity_words_per_day)}</Td>
                    <Td className="tabular hidden text-right sm:table-cell">{f.num(v.open_assignments ?? 0)}</Td>
                    <Td className="tabular hidden lg:table-cell">{v.rating ?? "–"}</Td>
                    <Td className="hidden xl:table-cell">
                      {v.nda_signed ? <Badge tone="ok">{t("app.vendors.signed")}</Badge> : <span className="text-faint">–</span>}
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
