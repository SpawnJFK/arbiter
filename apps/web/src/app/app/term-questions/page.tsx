import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { QuestionsList } from "./questions";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.termQuestions.termQuestions") };
}

export default async function TermQuestionsPage() {
  const { t } = await getI18n();
  const [questions, glossaries] = await withAuth(
    (api) => Promise.all([api.termQuestions({ limit: 200 }), api.glossaries({ limit: 200 })]),
    "/app/term-questions",
  );
  return (
    <>
      <PageHeader
        title={t("app.termQuestions.termQuestions")}
        description={t("app.termQuestions.whenReviewersOrTheSenate")}
      />
      <QuestionsList initial={questions.items} glossaries={glossaries.items} />
    </>
  );
}
