import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { getMe } from "@/lib/server-api";
import { NewProjectWizard } from "./wizard";

export const metadata: Metadata = { title: "New project" };

export default async function NewProjectPage() {
  const { org } = await getMe();
  return (
    <>
      <PageHeader
        title="New project"
        description="Upload a file, pick languages, then compare tiers before anything runs. You are not charged until you start the project."
      />
      <NewProjectWizard defaultTier={org?.default_tier ?? "hybrid"} regulated={org?.regulated ?? false} vertical={org?.vertical ?? null} />
    </>
  );
}
