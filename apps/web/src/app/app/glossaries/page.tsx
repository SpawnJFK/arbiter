import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { num } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { NewGlossaryButton } from "./new-glossary";

export const metadata: Metadata = { title: "Glossaries" };

export default async function GlossariesPage() {
  const { items } = await withAuth((api) => api.glossaries({ limit: 200 }), "/app/glossaries");
  return (
    <>
      <PageHeader
        title="Glossaries"
        description="Terms are checked on every segment. Each change bumps the version; running jobs keep the version they started with."
        actions={<NewGlossaryButton />}
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title="No glossaries" description="Create one, or import a CSV or TBX file into a new glossary." action={<NewGlossaryButton />} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>Content type</Th>
                <Th className="text-right">Terms</Th>
                <Th className="text-right">Version</Th>
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
                  <Td className="text-muted">{g.content_type ? contentTypeLabel(g.content_type) : "All content"}</Td>
                  <Td className="tabular text-right">{num(g.term_count)}</Td>
                  <Td className="tabular text-right text-muted">v{g.version}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
