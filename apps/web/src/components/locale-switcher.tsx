"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { useI18n } from "@/lib/i18n/client";
import { Icons } from "./icons";

/** Interface language picker for the user menu. Hidden while only one language is enabled. */
export function LocaleSwitcher() {
  const { t, locale, locales } = useI18n();
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [saving, setSaving] = useState(false);
  if (locales.length < 2) return null;

  async function choose(next: string) {
    setSaving(true);
    try {
      await fetch("/api/locale", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ locale: next }) });
    } finally {
      setSaving(false);
    }
    startTransition(() => router.refresh());
  }

  return (
    <label className="mt-1 flex items-center gap-2 rounded-md px-2 py-1 text-[12.5px] text-muted">
      <Icons.globe className="size-3.5 shrink-0 text-faint" />
      <span className="sr-only">{t("components.localeSwitcher.language")}</span>
      <select
        value={locale}
        disabled={saving || pending}
        onChange={(e) => void choose(e.target.value)}
        className="h-7 min-w-0 flex-1 rounded-md border border-border bg-surface px-1.5 text-[12.5px] text-fg"
        aria-label={t("components.localeSwitcher.language")}
      >
        {locales.map((l) => (
          <option key={l.locale} value={l.locale}>
            {l.name}
          </option>
        ))}
      </select>
    </label>
  );
}
