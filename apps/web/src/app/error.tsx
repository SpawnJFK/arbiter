"use client";

import { useI18n } from "@/lib/i18n/client";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useI18n();
  return (
    <main id="main" className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        title={t("error.somethingWentWrong")}
        description={error.message || t("error.theRequestFailedTryAgain")}
        action={<Button onClick={reset}>{t("error.tryAgain")}</Button>}
      />
    </main>
  );
}
