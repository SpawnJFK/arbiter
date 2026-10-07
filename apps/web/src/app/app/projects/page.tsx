import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { TIER_LABEL } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export const metadata: Metadata = { title: "Projects" };

export default async function ProjectsPage() {
  const { items } = await withAuth((api) => api.projects({ limit: 100 }), "/app/projects");
  return (
    <>
      <PageHeader
        title="Projects"
        description="One project per uploaded file; each target language runs as its own job."
        actions={
          <ButtonLink href="/app/projects/new" variant="primary">
            <Icons.plus className="size-4" /> New project
          </ButtonLink>
        }
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="Upload a file to see the price for each tier and the share of segments we expect to approve without a human."
            action={<ButtonLink href="/app/projects/new" variant="primary">New project</ButtonLink>}
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>Languages</Th>
                <Th>Tier</Th>
                <Th className="hidden md:table-cell">Content</Th>
                <Th className="hidden sm:table-cell">Due</Th>
                <Th className="hidden lg:table-cell">Created</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((p) => (
                <Tr key={p.id}>
                  <Td className="font-medium">
                    <Link href={`/app/projects/${p.id}`} className="hover:text-accent hover:underline">
                      {p.name}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap text-muted">
                    <span className="font-mono text-[12.5px]">{p.source_lang}</span> →{" "}
                    <span className="font-mono text-[12.5px]">{p.target_langs.join(", ")}</span>
                  </Td>
                  <Td>
                    <Badge tone={p.tier === "hybrid" || p.tier === "full" ? "violet" : "accent"}>{TIER_LABEL[p.tier]}</Badge>
                  </Td>
                  <Td className="hidden text-muted md:table-cell">{contentTypeLabel(p.content_type)}</Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={p.due_at} mode="relative" />
                  </Td>
                  <Td className="hidden text-muted lg:table-cell">
                    <Time iso={p.created_at} />
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
