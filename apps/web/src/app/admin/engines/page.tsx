import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { EngineKeys } from "@/components/engines/engine-keys";
import { engineNames } from "@/components/engines/engine-names";
import { EngineRoutes } from "@/components/engines/engine-routes";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("engines.admin.title") };
}

export default async function AdminEnginesPage() {
  const { t } = await getI18n();
  const [catalog, keys, routes] = await withAuth(
    (api) => Promise.all([api.engineCatalog("platform"), api.engineCredentials("platform"), api.engineRoutes("platform")]),
    "/admin/engines",
  );
  return (
    <>
      <PageHeader title={t("engines.admin.title")} description={t("engines.admin.description")} />
      <div className="space-y-4">
        <EngineKeys scope="platform" catalog={catalog.items} initial={keys.items} />
        <EngineRoutes scope="platform" initial={routes.items} engineNames={engineNames(catalog.items, keys.items)} />
      </div>
    </>
  );
}
