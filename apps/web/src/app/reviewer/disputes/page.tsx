import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { DisputeForm } from "./dispute-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewer.disputes.disputes") };
}

export default async function DisputesPage({ searchParams }: { searchParams: Promise<{ task?: string }> }) {
  const { t } = await getI18n();
  const { task } = await searchParams;
  return (
    <>
      <PageHeader
        title={t("reviewer.disputes.disputes")}
        description={t("reviewer.disputes.thinkAScoreAControl")}
      />
      <DisputeForm initialTaskId={task ?? ""} />
    </>
  );
}
