import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/ui/misc";
import { humanize } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { TestRunner } from "./test-runner";

export const metadata: Metadata = { title: "Test" };

export default async function TestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { items } = await withAuth((api) => api.reviewerTests(), `/reviewer/tests/${id}`);
  const test = items.find((t) => t.id === id);
  if (!test) notFound();
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/reviewer/tests" className="hover:text-fg">
            Tests
          </Link>
        }
        title={`${test.source_lang} → ${test.target_lang} · ${contentTypeLabel(test.domain)}`}
        description={`${humanize(test.kind)} test · ${test.time_limit_min} minutes`}
      />
      <TestRunner test={test} />
    </>
  );
}
