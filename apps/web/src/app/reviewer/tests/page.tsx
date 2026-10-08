import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { StatusBadge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewer.tests.tests") };
}

export default async function TestsPage() {
  const { t } = await getI18n();
  const { items } = await withAuth((api) => api.reviewerTests(), "/reviewer/tests");
  return (
    <>
      <PageHeader
        title={t("reviewer.tests.tests")}
        description={t("reviewer.tests.eachPairAndDomainUnlocks")}
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title={t("reviewer.tests.noTests")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("reviewer.tests.pair")}</Th>
                <Th>{t("reviewer.tests.domain")}</Th>
                <Th>{t("reviewer.tests.kind")}</Th>
                <Th className="text-right">{t("reviewer.tests.timeLimit")}</Th>
                <Th>{t("reviewer.tests.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("reviewer.tests.action")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {items.map((item) => (
                <Tr key={item.id}>
                  <Td className="font-mono text-[13px]">
                    {item.source_lang} → {item.target_lang}
                  </Td>
                  <Td>{contentTypeLabel(t, item.domain)}</Td>
                  <Td className="text-muted">{t.enumLabel(item.kind)}</Td>
                  <Td className="tabular text-right">{t("reviewer.tests.min", { time_limit_min: item.time_limit_min })}</Td>
                  <Td>
                    <StatusBadge status={item.status} />
                  </Td>
                  <Td className="text-right">
                    {item.status === "available" ? (
                      <ButtonLink href={`/reviewer/tests/${item.id}`} size="sm" variant="primary">
                        {t("reviewer.tests.start")}
                      </ButtonLink>
                    ) : item.status === "locked" ? (
                      <span className="text-[12.5px] text-faint">{t("reviewer.tests.unlocksAtAHigherLevel")}</span>
                    ) : null}
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
