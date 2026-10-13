"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { TmAlign } from "./tm-align";
import { TmEditor } from "./tm-editor";
import { TmQaView } from "./tm-qa";
import { TmScreen } from "./tm-screen";

type Tab = "search" | "editor" | "align" | "qa";

export function TmTabs({ canEdit }: { canEdit: boolean }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("search");
  const tabs: [Tab, string][] = [
    ["search", t("app.tm.tabs.search")],
    ["editor", t("app.tm.tabs.editor")],
    ["align", t("app.tm.tabs.align")],
    ["qa", t("app.tm.tabs.qa")],
  ];
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label={t("app.tm.tabs.label")} className="flex gap-1 border-b border-border">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-[13.5px] font-medium",
              tab === key ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "search" && <TmScreen />}
      {tab === "editor" && <TmEditor canEdit={canEdit} />}
      {tab === "align" && <TmAlign canEdit={canEdit} />}
      {tab === "qa" && <TmQaView />}
    </div>
  );
}
