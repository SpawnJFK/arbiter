import { getI18n } from "@/lib/i18n/server";
import { Skeleton } from "@/components/ui/misc";

export default async function Loading() {
  const { t } = await getI18n();
  return (
    <div aria-busy="true" aria-label={t("app.loading.loading")}>
      <Skeleton className="mb-2 h-6 w-48" />
      <Skeleton className="mb-6 h-4 w-80" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
