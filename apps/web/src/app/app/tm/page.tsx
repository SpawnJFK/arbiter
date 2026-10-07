import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { TmScreen } from "./tm-screen";

export const metadata: Metadata = { title: "Translation memory" };

export default function TmPage() {
  return (
    <>
      <PageHeader
        title="Translation memory"
        description="Approved segments are stored automatically. Import existing TMX files to reuse past translations from day one."
      />
      <TmScreen />
    </>
  );
}
