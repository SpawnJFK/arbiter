import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { DisputeForm } from "./dispute-form";

export const metadata: Metadata = { title: "Disputes" };

export default async function DisputesPage({ searchParams }: { searchParams: Promise<{ task?: string }> }) {
  const { task } = await searchParams;
  return (
    <>
      <PageHeader
        title="Disputes"
        description="Think a score, a control-sample verdict or a ledger adjustment on one of your tasks is wrong? Open a dispute. A platform reviewer decides, and the ledger is corrected if you are right."
      />
      <DisputeForm initialTaskId={task ?? ""} />
    </>
  );
}
