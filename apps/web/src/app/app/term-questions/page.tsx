import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { QuestionsList } from "./questions";

export const metadata: Metadata = { title: "Term questions" };

export default async function TermQuestionsPage() {
  const [questions, glossaries] = await withAuth(
    (api) => Promise.all([api.termQuestions({ limit: 200 }), api.glossaries({ limit: 200 })]),
    "/app/term-questions",
  );
  return (
    <>
      <PageHeader
        title="Term questions"
        description="When reviewers or the senate are unsure how a term should be translated, they ask here. Your answer applies to running jobs and can go straight into a glossary."
      />
      <QuestionsList initial={questions.items} glossaries={glossaries.items} />
    </>
  );
}
