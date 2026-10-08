import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/ui/misc";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { TestRunner } from "./test-runner";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewer.tests.detail.test") };
}

export default async function TestPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const { items } = await withAuth((api) => api.reviewerTests(), `/reviewer/tests/${id}`);
  const test = items.find((item) => item.id === id);
  if (!test) notFound();
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/reviewer/tests" className="hover:text-fg">
            {t("reviewer.tests.detail.tests")}
          </Link>
        }
        title={t("reviewer.tests.detail.text", { source_lang: test.source_lang, target_lang: test.target_lang, domain: contentTypeLabel(t, test.domain) })}
        description={t("reviewer.tests.detail.testMinutes", { kind: t.enumLabel(test.kind), time_limit_min: test.time_limit_min })}
      />
      <TestRunner test={test} />
    </>
  );
}
