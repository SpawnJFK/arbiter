import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui/misc";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { TermsManager } from "./terms-manager";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.glossaries.detail.glossary") };
}

export default async function GlossaryPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const next = `/app/glossaries/${id}`;
  // The contract has no GET /glossaries/{id}; find it in the list.
  const [list, terms] = await withAuth((api) => Promise.all([api.glossaries({ limit: 200 }), api.terms(id, { limit: 200 })]), next);
  const glossary = list.items.find((g) => g.id === id);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/glossaries" className="hover:text-fg">
            {t("app.glossaries.detail.glossaries")}
          </Link>
        }
        title={glossary?.name ?? t("app.glossaries.detail.glossary")}
        description={glossary ? t("app.glossaries.detail.version", { contentType: glossary.content_type ? contentTypeLabel(t, glossary.content_type) : t("app.glossaries.allContent"), version: glossary.version }) : undefined}
      />
      <TermsManager glossaryId={id} initial={terms} />
    </>
  );
}
