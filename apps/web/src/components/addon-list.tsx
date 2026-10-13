"use client";

import { useI18n } from "@/lib/i18n/client";
import { Badge } from "@/components/ui/badge";
import type { AddonInfo } from "@/lib/platform-api";

/** Add-ons of the org, read-only everywhere: a plan or a billing override changes them (D-077). */
export function AddonList({ addons }: { addons: AddonInfo[] }) {
  const { t } = useI18n();
  const name = (a: AddonInfo) => (t.has(`platform.addon.${a.key}.name`) ? t(`platform.addon.${a.key}.name`) : a.name);
  const moduleName = (key: string) => (t.has(`platform.module.${key}.name`) ? t(`platform.module.${key}.name`) : key);
  return (
    <ul className="divide-y divide-border">
      {addons.map((a) => (
        <li key={a.key} className="flex items-start gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13.5px] font-medium text-fg">{name(a)}</span>
              <span className="font-mono text-[11.5px] text-faint">{a.key}</span>
            </div>
            <p className="mt-0.5 text-[13px] text-muted">{t(`platform.addon.${a.key}.description`)}</p>
            <p className="mt-0.5 text-[12px] text-faint">{t("platform.addons.partOf", { module: moduleName(a.module) })}</p>
          </div>
          <Badge tone={a.enabled ? "ok" : "neutral"} dot className="mt-0.5 shrink-0">
            {a.enabled ? t("platform.modules.enabled") : t("platform.modules.notEnabled")}
          </Badge>
        </li>
      ))}
    </ul>
  );
}
