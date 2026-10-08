import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { ApplyForm } from "./apply-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewers.apply.applyAsAReviewer") };
}

export default async function ApplyPage() {
  const { t } = await getI18n();
  return (
    <div className="mx-auto grid max-w-5xl gap-10 px-4 py-12 md:grid-cols-[1fr_1.3fr] md:px-6 md:py-16">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("reviewers.apply.reviewTranslationsWhereItMatters")}</h1>
        <p className="mt-2 text-[14.5px] leading-relaxed text-muted">
          {t("reviewers.apply.arbiterSendsYouTheSegments")}
        </p>
        <ol className="mt-6 space-y-4 text-[14px]">
          {["apply", "test", "cockpit", "paid"].map((step, i) => (
            <li key={step} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-[12px] font-semibold text-accent">
                {i + 1}
              </span>
              <div>
                <div className="font-medium">{t(`reviewers.apply.step.${step}.title`)}</div>
                <div className="text-muted">{t(`reviewers.apply.step.${step}.body`)}</div>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-[13.5px] text-muted">
          {t("reviewers.apply.alreadyApplied")} <Link href="/login" className="font-medium text-accent hover:underline">{t("reviewers.apply.signIn")}</Link>
        </p>
      </div>
      <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
        <ApplyForm />
      </div>
    </div>
  );
}
