import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { getServerApi } from "@/lib/server-api";
import type { PlansResponse } from "@/lib/types";
import { PricingTable } from "./pricing-table";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("pricing.metaTitle"), description: t("pricing.metaDescription") };
}

/** Public pricing, generated from the plans catalog (GET /v1/billing/plans). No invented logos or numbers. */
export default async function PricingPage() {
  const { t } = await getI18n();
  let plans: PlansResponse | null = null;
  try {
    plans = await (await getServerApi()).plans();
  } catch {
    plans = null;
  }
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 md:px-6 md:py-16">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight text-fg md:text-3xl">{t("pricing.title")}</h1>
        <p className="mt-2 text-[15px] text-muted">{t("pricing.lead")}</p>
      </div>
      {plans ? (
        <PricingTable plans={plans} />
      ) : (
        <p className="mt-10 text-[14px] text-muted">{t("pricing.unavailable")}</p>
      )}
    </div>
  );
}
