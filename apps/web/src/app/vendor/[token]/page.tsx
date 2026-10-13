import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { Logo } from "@/components/icons";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/misc";
import { backendFetch } from "@/lib/backend";
import type { PortalView } from "@/lib/vendor-types";
import { Workbench } from "./workbench";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("vendor.workbench.title"), robots: { index: false, follow: false } };
}

/** The vendor workbench: no login, the signed link from the offer e-mail is the key (module pm). */
export default async function VendorWorkbenchPage({ params }: { params: Promise<{ token: string }> }) {
  const { t } = await getI18n();
  const { token } = await params;
  const res = await backendFetch(`/vendor-portal/${encodeURIComponent(token)}`, { token: null });
  const view = res.ok ? ((await res.json()) as PortalView) : null;
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border bg-surface/80">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 md:px-6">
          <Logo className="size-6" />
          <span className="font-semibold tracking-tight">{t("layout.arbiter")}</span>
          {view && <span className="ml-2 truncate text-[13px] text-muted">{t("vendor.workbench.for", { org: view.organization })}</span>}
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-6">
        {view ? (
          <Workbench token={token} initial={view} />
        ) : (
          <Card>
            <EmptyState title={t("vendor.workbench.invalidLink")} description={t("vendor.workbench.invalidLinkHint")} />
          </Card>
        )}
      </main>
    </div>
  );
}
