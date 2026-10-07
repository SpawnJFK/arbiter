import type { Metadata } from "next";
import { StatusBadge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { humanize } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export const metadata: Metadata = { title: "Tests" };

export default async function TestsPage() {
  const { items } = await withAuth((api) => api.reviewerTests(), "/reviewer/tests");
  return (
    <>
      <PageHeader
        title="Tests"
        description="Each pair and domain unlocks with a timed test: review machine output, fix it, and annotate the errors you find on the MQM scale."
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title="No tests" />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Pair</Th>
                <Th>Domain</Th>
                <Th>Kind</Th>
                <Th className="text-right">Time limit</Th>
                <Th>Status</Th>
                <Th className="text-right">
                  <span className="sr-only">Action</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {items.map((t) => (
                <Tr key={t.id}>
                  <Td className="font-mono text-[13px]">
                    {t.source_lang} → {t.target_lang}
                  </Td>
                  <Td>{contentTypeLabel(t.domain)}</Td>
                  <Td className="text-muted">{humanize(t.kind)}</Td>
                  <Td className="tabular text-right">{t.time_limit_min} min</Td>
                  <Td>
                    <StatusBadge status={t.status} />
                  </Td>
                  <Td className="text-right">
                    {t.status === "available" ? (
                      <ButtonLink href={`/reviewer/tests/${t.id}`} size="sm" variant="primary">
                        Start
                      </ButtonLink>
                    ) : t.status === "locked" ? (
                      <span className="text-[12.5px] text-faint">Unlocks at a higher level</span>
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
