"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { IS_MOCK } from "@/lib/config";
import { Icons, Logo } from "./icons";
import { LocaleSwitcher } from "./locale-switcher";

export type IconName = keyof typeof Icons;
export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  exact?: boolean;
}
export interface NavSection {
  label?: string;
  items: NavItem[];
}

export function AppShell({
  sections,
  user,
  context,
  children,
}: {
  sections: NavSection[];
  user: { name: string; email: string; role: string };
  context?: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    await fetch("/api/session", { method: "DELETE" }).catch(() => null);
    router.replace("/login");
    router.refresh();
  }

  // The most specific matching item wins (e.g. /app/projects/new highlights "New project" only).
  const matches = (item: NavItem) =>
    item.exact ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
  const best = sections
    .flatMap((x) => x.items)
    .filter(matches)
    .sort((x, y) => y.href.length - x.href.length)[0];
  const isActive = (item: NavItem) => best?.href === item.href;

  const nav = (
    <nav aria-label={t("components.shell.main")} className="flex flex-1 flex-col gap-4 overflow-y-auto px-2 py-3">
      {sections.map((s, i) => (
        <div key={i}>
          {s.label && <div className="px-2 pb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">{s.label}</div>}
          <ul className="flex flex-col gap-px">
            {s.items.map((item) => {
              const Icon = Icons[item.icon];
              const active = isActive(item);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={() => setOpen(false)}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex h-8 items-center gap-2.5 rounded-md px-2 text-[13.5px] transition-colors",
                      active ? "bg-hover font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg",
                    )}
                  >
                    <Icon className={cn("size-4 shrink-0", active ? "text-accent" : "text-faint")} />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );

  const footer = (
    <div className="border-t border-border p-2">
      <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-[12px] font-semibold text-accent">
          {initials(user.name)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-fg">{user.name}</div>
          <div className="truncate text-[12px] text-faint">
            {user.email} · {t.enumLabel(user.role)}
          </div>
        </div>
        <button
          type="button"
          onClick={signOut}
          disabled={signingOut}
          className="rounded-md p-1.5 text-faint hover:bg-hover hover:text-fg"
          aria-label={t("components.shell.signOut")}
          title={t("components.shell.signOut")}
        >
          <Icons.logout className="size-4" />
        </button>
      </div>
      <LocaleSwitcher />
    </div>
  );

  return (
    <div className="flex min-h-dvh">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
        <Brand context={context} />
        {nav}
        {footer}
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button className="absolute inset-0 bg-black/40" aria-label={t("components.shell.closeMenu")} onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-border bg-surface shadow-pop">
            <Brand context={context} />
            {nav}
            {footer}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-surface/90 px-3 backdrop-blur md:hidden">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded-md p-1.5 text-muted hover:bg-hover"
            aria-label={t("components.shell.openMenu")}
            aria-expanded={open}
          >
            <Icons.menu className="size-5" />
          </button>
          <Logo className="size-5" />
          <span className="text-sm font-semibold">{t("components.shell.arbiter")}</span>
          {context && <span className="truncate text-[13px] text-muted">· {context}</span>}
        </header>
        {IS_MOCK && (
          <div className="border-b border-warn/30 bg-warn-subtle px-4 py-1 text-center text-[12px] text-warn">
            {t("components.shell.demoModeDataComesFrom")}
          </div>
        )}
        <main id="main" className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}

function Brand({ context }: { context?: string }) {
  const { t } = useI18n();
  return (
    <div className="flex h-12 items-center gap-2 border-b border-border px-4">
      <Logo className="size-5" />
      <span className="text-[14px] font-semibold tracking-tight">{t("components.shell.arbiter")}</span>
      {context && <span className="ml-auto max-w-[110px] truncate text-[12px] text-faint">{context}</span>}
    </div>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]!.toUpperCase())
    .join("");
}
