import Link from "next/link";
import { Logo } from "@/components/icons";
import { ButtonLink } from "@/components/ui/button";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border bg-surface/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 md:px-6">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <Logo className="size-6" />
            Arbiter
          </Link>
          <nav aria-label="Site" className="ml-auto flex items-center gap-1 sm:gap-2">
            <Link href="/reviewers/apply" className="hidden rounded-md px-2.5 py-1.5 text-[13.5px] text-muted hover:text-fg sm:block">
              For reviewers
            </Link>
            <Link href="/login" className="rounded-md px-2.5 py-1.5 text-[13.5px] text-muted hover:text-fg">
              Sign in
            </Link>
            <ButtonLink href="/register" variant="primary" size="sm">
              Create account
            </ButtonLink>
          </nav>
        </div>
      </header>
      <main id="main" className="flex-1">
        {children}
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-6 text-[13px] text-muted md:px-6">
          <span>Arbiter</span>
          <Link href="/reviewers/apply" className="hover:text-fg">
            Become a reviewer
          </Link>
          <Link href="/login" className="hover:text-fg">
            Sign in
          </Link>
        </div>
      </footer>
    </div>
  );
}
