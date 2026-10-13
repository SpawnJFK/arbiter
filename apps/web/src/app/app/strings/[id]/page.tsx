import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { StringWorkspace } from "./workspace";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.strings.title") };
}

export default async function StringProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StringWorkspace projectId={id} />;
}
