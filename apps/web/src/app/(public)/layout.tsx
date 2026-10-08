import { getI18n } from "@/lib/i18n/server";
import Link from "next/link";
import { Logo } from "@/components/icons";
import { ButtonLink } from "@/components/ui/button";

export default async function PublicLayout({ children }: { children: React.ReactNode }) {
  const { t } = await getI18n();
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border bg-surface/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 md:px-6">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <Logo className="size-6" />
            {t("layout.arbiter")}
          </Link>
          <nav aria-label={t("layout.site")} className="ml-auto flex items-center gap-1 sm:gap-2">
            <Link href="/reviewers/apply" className="hidden rounded-md px-2.5 py-1.5 text-[13.5px] text-muted hover:text-fg sm:block">
              {t("layout.forReviewers")}
            </Link>
            <Link href="/login" className="rounded-md px-2.5 py-1.5 text-[13.5px] text-muted hover:text-fg">
              {t("layout.signIn")}
            </Link>
            <ButtonLink href="/register" variant="primary" size="sm">
              {t("layout.createAccount")}
            </ButtonLink>
          </nav>
        </div>
      </header>
      <main id="main" className="flex-1">
        {children}
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-6 text-[13px] text-muted md:px-6">
          <span>{t("layout.arbiter")}</span>
          <Link href="/reviewers/apply" className="hover:text-fg">
            {t("layout.becomeAReviewer")}
          </Link>
          <Link href="/login" className="hover:text-fg">
            {t("layout.signIn")}
          </Link>
        </div>
      </footer>
    </div>
  );
}
