"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

export function SubNav({ items, label }: { items: { href: string; label: string }[]; label: string }) {
  const pathname = usePathname();
  return (
    <nav aria-label={label} className="mb-5 overflow-x-auto border-b border-border">
      <ul className="flex gap-1">
        {items.map((i) => {
          const active = pathname === i.href;
          return (
            <li key={i.href}>
              <Link
                href={i.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px inline-flex h-9 items-center whitespace-nowrap border-b-2 px-3 text-[13.5px] transition-colors",
                  active ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg",
                )}
              >
                {i.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
