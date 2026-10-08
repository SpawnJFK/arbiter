import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { NewGlossaryButton } from "./new-glossary";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.glossaries.glossaries") };
}

export default async function GlossariesPage() {
  const { f, t } = await getI18n();
  const { items } = await withAuth((api) => api.glossaries({ limit: 200 }), "/app/glossaries");
  return (
    <>
      <PageHeader
        title={t("app.glossaries.glossaries")}
        description={t("app.glossaries.termsAreCheckedOnEvery")}
        actions={<NewGlossaryButton />}
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title={t("app.glossaries.noGlossaries")} description={t("app.glossaries.createOneOrImportA")} action={<NewGlossaryButton />} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.glossaries.name")}</Th>
                <Th>{t("app.glossaries.contentType")}</Th>
                <Th className="text-right">{t("app.glossaries.terms")}</Th>
                <Th className="text-right">{t("app.glossaries.version")}</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((g) => (
                <Tr key={g.id}>
                  <Td>
                    <Link href={`/app/glossaries/${g.id}`} className="font-medium hover:text-accent hover:underline">
                      {g.name}
                    </Link>
                  </Td>
                  <Td className="text-muted">{g.content_type ? contentTypeLabel(t, g.content_type) : t("app.glossaries.allContent")}</Td>
                  <Td className="tabular text-right">{f.num(g.term_count)}</Td>
                  <Td className="tabular text-right text-muted">{t("app.glossaries.versionShort", { version: g.version })}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
