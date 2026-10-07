import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui/misc";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { TermsManager } from "./terms-manager";

export const metadata: Metadata = { title: "Glossary" };

export default async function GlossaryPage({ params }: { params: Promise<{ id: string }> }) {
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
            Glossaries
          </Link>
        }
        title={glossary?.name ?? "Glossary"}
        description={glossary ? `${glossary.content_type ? contentTypeLabel(glossary.content_type) : "All content"} · version ${glossary.version}` : undefined}
      />
      <TermsManager glossaryId={id} initial={terms} />
    </>
  );
}
