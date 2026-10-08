import { getI18n } from "@/lib/i18n/server";
import { Icons } from "@/components/icons";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";

export default async function Landing() {
  const { t } = await getI18n();
  return (
    <>
      <section className="mx-auto grid max-w-6xl gap-10 px-4 pb-14 pt-14 md:grid-cols-[1.05fr_1fr] md:px-6 md:pt-20">
        <div>
          <p className="mb-3 text-[13px] font-medium text-accent">{t("page.aiNativeTranslationForBusinesses")}</p>
          <h1 className="text-[34px] font-semibold leading-[1.1] tracking-tight text-fg md:text-[44px]">
            {t("page.shipMachineTranslationOnlyWhere")}
          </h1>
          <p className="mt-4 max-w-xl text-[16px] leading-relaxed text-muted">
            {t("page.arbiterScoresEverySegmentLets")}
          </p>
          <div className="mt-7 flex flex-wrap gap-2">
            <ButtonLink href="/register" variant="primary">
              {t("page.createACompanyAccount")}
            </ButtonLink>
            <ButtonLink href="/reviewers/apply">{t("page.applyAsAReviewer")}</ButtonLink>
          </div>
        </div>
        <ExampleSegment />
      </section>

      <section className="border-y border-border bg-surface">
        <div className="mx-auto grid max-w-6xl gap-px px-4 md:grid-cols-3 md:px-6">
          {[
            {
              icon: Icons.upload,
              title: t("page.uploadAFile"),
              body: t("page.docxXlsxPptxHtmlMarkdown"),
            },
            {
              icon: Icons.scale,
              title: t("page.seeThePricePerTier"),
              body: t("page.eachTierShowsItsPrice"),
            },
            {
              icon: Icons.check,
              title: t("page.getEvidencePerSegment"),
              body: t("page.qualityScoreSenateVotesReviewer"),
            },
          ].map((s) => (
            <div key={s.title} className="py-8 md:px-6 md:first:pl-0 md:last:pr-0">
              <s.icon className="size-5 text-accent" />
              <h2 className="mt-3 text-[15px] font-semibold">{s.title}</h2>
              <p className="mt-1.5 text-[14px] leading-relaxed text-muted">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 md:px-6">
        <h2 className="text-xl font-semibold tracking-tight">{t("page.fourTiersOneRule")}</h2>
        <p className="mt-1.5 max-w-2xl text-[14.5px] text-muted">
          {t("page.aTierDecidesWhoGets")}
        </p>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(["auto", "ai_review", "hybrid", "full"] as const).map((item) => (
            <div key={item} className="rounded-lg border border-border bg-surface p-4 shadow-card">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">{t(`tier.${item}.label`)}</h3>
                {(item === "hybrid" || item === "full") && <Badge tone="violet">{t("page.humanReview")}</Badge>}
              </div>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">{t(`tier.${item}.blurb`)}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-[13px] text-muted">
          {t("page.regulatedContentMedicalLegalFinancial")}
        </p>
      </section>

      <section className="border-t border-border bg-surface">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-14 md:grid-cols-2 md:px-6">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">{t("page.builtForTheTeamsWho")}</h2>
            <ul className="mt-4 space-y-3 text-[14.5px] text-muted">
              {["thresholds", "glossaries", "tags", "api"].map((x) => (
                <li key={x} className="flex gap-2.5">
                  <Icons.check className="mt-0.5 size-4 shrink-0 text-ok" />
                  <span>{t(`page.feature.${x}`)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-border bg-bg p-5">
            <h2 className="text-[15px] font-semibold">{t("page.translatorsAndReviewers")}</h2>
            <p className="mt-1.5 text-[14px] leading-relaxed text-muted">
              {t("page.reviewSegmentsTheMachinesAre")}
            </p>
            <ButtonLink href="/reviewers/apply" className="mt-4" size="sm">
              {t("page.applyAsAReviewer")} <Icons.arrowRight className="size-3.5" />
            </ButtonLink>
          </div>
        </div>
      </section>
    </>
  );
}

async function ExampleSegment() {
  const { t } = await getI18n();
  return (
    <div className="self-center rounded-xl border border-border bg-surface shadow-pop" aria-label={t("page.exampleOfTheEvidenceRecorded")}>
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-[12.5px] font-medium text-muted">{t("page.exampleSegmentEnDe")}</span>
        <Badge tone="neutral">{t("page.illustration")}</Badge>
      </div>
      <div className="space-y-3 px-4 py-4">
        <div>
          <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("page.source")}</div>
          <TaggedText value="Press ⟦1⟧Start⟦/1⟧ to begin the infusion." className="text-[14.5px]" />
        </div>
        <div>
          <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{t("page.target")}</div>
          <TaggedText value="Drücken Sie ⟦1⟧Start⟦/1⟧, um die Infusion zu beginnen." className="text-[14.5px]" />
        </div>
      </div>
      <ol className="space-y-2.5 border-t border-border px-4 py-4 text-[13px]">
        {[
          { label: t("page.qualityEstimate"), detail: t("page.scoreFallsInsideTheUncertainty"), tone: "warn" as const, badge: t("page.uncertain") },
          { label: t("page.glossaryAndTagChecks"), detail: t("page.mandatoryTermPresentTagsIntact"), tone: "ok" as const, badge: t("page.pass") },
          { label: t("page.senateVote"), detail: t("page.threeAgentsReviewIndependentlyOne"), tone: "accent" as const, badge: t("page.approve") },
          { label: t("page.decision"), detail: t("page.shippedWithTheFullTrail"), tone: "ok" as const, badge: t("page.delivered") },
        ].map((s, i) => (
          <li key={s.label} className="flex items-start gap-3">
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-subtle text-[11px] font-semibold text-muted">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-fg">{s.label}</div>
              <div className="text-muted">{s.detail}</div>
            </div>
            <Badge tone={s.tone}>{s.badge}</Badge>
          </li>
        ))}
      </ol>
    </div>
  );
}
