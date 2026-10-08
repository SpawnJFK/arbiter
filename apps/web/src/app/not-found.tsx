import { getI18n } from "@/lib/i18n/server";
import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";

export default async function NotFound() {
  const { t } = await getI18n();
  return (
    <main id="main" className="flex min-h-dvh items-center justify-center">
      <EmptyState
        title={t("notFound.notFound")}
        description={t("notFound.thisPageDoesNotExist")}
        action={<ButtonLink href="/">{t("notFound.goHome")}</ButtonLink>}
      />
    </main>
  );
}
