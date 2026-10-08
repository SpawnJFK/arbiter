import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.projects.projects") };
}

export default async function ProjectsPage() {
  const { t } = await getI18n();
  const { items } = await withAuth((api) => api.projects({ limit: 100 }), "/app/projects");
  return (
    <>
      <PageHeader
        title={t("app.projects.projects")}
        description={t("app.projects.oneProjectPerUploadedFile")}
        actions={
          <ButtonLink href="/app/projects/new" variant="primary">
            <Icons.plus className="size-4" /> {t("app.projects.newProject")}
          </ButtonLink>
        }
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState
            title={t("app.projects.noProjectsYet")}
            description={t("app.projects.uploadAFileToSee")}
            action={<ButtonLink href="/app/projects/new" variant="primary">{t("app.projects.newProject")}</ButtonLink>}
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.projects.name")}</Th>
                <Th>{t("app.projects.languages")}</Th>
                <Th>{t("app.projects.tier")}</Th>
                <Th className="hidden md:table-cell">{t("app.projects.content")}</Th>
                <Th className="hidden sm:table-cell">{t("app.projects.due")}</Th>
                <Th className="hidden lg:table-cell">{t("app.projects.created")}</Th>
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
                    <Badge tone={p.tier === "hybrid" || p.tier === "full" ? "violet" : "accent"}>{t(`tier.${p.tier}.label`)}</Badge>
                  </Td>
                  <Td className="hidden text-muted md:table-cell">{contentTypeLabel(t, p.content_type)}</Td>
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
