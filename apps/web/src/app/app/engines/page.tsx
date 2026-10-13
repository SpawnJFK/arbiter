import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { EngineBudgets } from "@/components/engines/engine-budgets";
import { EngineKeys } from "@/components/engines/engine-keys";
import { engineNames } from "@/components/engines/engine-names";
import { EngineRoutes } from "@/components/engines/engine-routes";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Callout, EmptyState, PageHeader } from "@/components/ui/misc";
import { ApiError, type Api } from "@/lib/api";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("engines.page.title") };
}

async function load(api: Api) {
  try {
    return await Promise.all([
      api.engineCatalog(),
      api.engineCredentials(),
      api.engineRoutes(),
      api.engineBudgets(),
      api.customModels().catch(() => ({ items: [], next_offset: null })),
    ]);
  } catch (e) {
    // module "engine" disabled (404) or no permission to manage engines (403)
    if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return null;
    throw e;
  }
}

export default async function EnginesPage() {
  const { t } = await getI18n();
  const data = await withAuth(load, "/app/engines");
  if (!data) {
    return (
      <>
        <PageHeader title={t("engines.page.title")} />
        <EmptyState title={t("engines.page.unavailable")} description={t("engines.page.unavailableDescription")} />
      </>
    );
  }
  const [catalog, keys, routes, budgets, models] = data;
  const providers = catalog.items.filter((c) => !c.capabilities.includes("training")).map((c) => c.provider);
  return (
    <>
      <PageHeader
        title={t("engines.page.title")}
        description={t("engines.page.description")}
        actions={
          <>
            <Badge tone={catalog.processing_region === "eu" ? "ok" : "neutral"}>
              {catalog.processing_region === "eu" ? t("engines.page.regionEu") : t("engines.page.regionGlobal")}
            </Badge>
            <ButtonLink href="/app/settings" size="sm" variant="ghost">
              {t("engines.page.changeRegion")}
            </ButtonLink>
          </>
        }
      />
      <div className="space-y-4">
        {catalog.processing_region === "eu" && <Callout tone="info">{t("engines.page.euExplainer")}</Callout>}
        <EngineKeys scope="org" catalog={catalog.items} initial={keys.items} />
        <EngineRoutes scope="org" initial={routes.items} engineNames={engineNames(catalog.items, keys.items, models.items)} />
        <EngineBudgets initial={budgets.items} providers={providers} currency={catalog.currency} />
        <p className="text-[12.5px] text-muted">{t("engines.page.priceNote")}</p>
      </div>
    </>
  );
}
