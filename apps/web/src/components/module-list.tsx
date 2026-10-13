"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { ModuleInfo } from "@/lib/platform-api";

/**
 * Module catalog. Read-only by default (customer Settings > Modules); with `orgId` it becomes
 * the platform admin editor (PUT /admin/orgs/{id}/modules). Dependencies are enforced here and
 * by the API: enabling a module turns on what it needs, disabling one turns off its dependents.
 */
export function ModuleList({ catalog, orgId }: { catalog: ModuleInfo[]; orgId?: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const [saved, setSaved] = useState(catalog);
  const [chosen, setChosen] = useState(() => new Set(catalog.filter((m) => m.enabled).map((m) => m.key)));
  const [busy, setBusy] = useState(false);
  const editable = Boolean(orgId);
  const dirty = saved.some((m) => m.enabled !== chosen.has(m.key));

  const name = (m: ModuleInfo) => (t.has(`platform.module.${m.key}.name`) ? t(`platform.module.${m.key}.name`) : m.name);

  function toggle(m: ModuleInfo, on: boolean) {
    const next = new Set(chosen);
    if (on) {
      next.add(m.key);
      m.depends_on.forEach((d) => next.add(d));
    } else {
      next.delete(m.key);
      for (const other of saved) if (other.depends_on.includes(m.key)) next.delete(other.key);
    }
    setChosen(next);
  }

  async function save() {
    if (!orgId) return;
    setBusy(true);
    try {
      const out = await api.setOrgModules(orgId, saved.filter((m) => chosen.has(m.key)).map((m) => m.key));
      setSaved(out.catalog);
      setChosen(new Set(out.enabled));
      toast.success(t("platform.modules.saved"));
    } catch (err) {
      toast.error(t("platform.modules.couldNotSave"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ul className="divide-y divide-border">
        {saved.map((m) => {
          const on = chosen.has(m.key);
          const id = `module-${m.key}`;
          return (
            <li key={m.key} className="flex items-start gap-3 px-4 py-3">
              {editable && (
                <input
                  id={id}
                  type="checkbox"
                  className="mt-1 size-4 shrink-0 accent-[var(--accent)]"
                  checked={on}
                  onChange={(e) => toggle(m, e.target.checked)}
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <label htmlFor={editable ? id : undefined} className="text-[13.5px] font-medium text-fg">
                    {name(m)}
                  </label>
                  <span className="font-mono text-[11.5px] text-faint">{m.key}</span>
                </div>
                <p className="mt-0.5 text-[13px] text-muted">{t(`platform.module.${m.key}.description`)}</p>
                {m.depends_on.length > 0 && (
                  <p className="mt-0.5 text-[12px] text-faint">
                    {t("platform.modules.requires", {
                      modules: m.depends_on.map((d) => (t.has(`platform.module.${d}.name`) ? t(`platform.module.${d}.name`) : d)).join(", "),
                    })}
                  </p>
                )}
              </div>
              <Badge tone={m.enabled ? "ok" : "neutral"} dot className="mt-0.5 shrink-0">
                {m.enabled ? t("platform.modules.enabled") : t("platform.modules.notEnabled")}
              </Badge>
            </li>
          );
        })}
      </ul>
      {editable && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-4 py-3">
          {dirty && <span className="mr-auto text-[12.5px] text-warn">{t("platform.modules.unsaved")}</span>}
          <Button
            variant="ghost"
            disabled={!dirty || busy}
            onClick={() => setChosen(new Set(saved.filter((m) => m.enabled).map((m) => m.key)))}
          >
            {t("platform.common.reset")}
          </Button>
          <Button variant="primary" loading={busy} disabled={!dirty} onClick={save}>
            {t("platform.modules.save")}
          </Button>
        </div>
      )}
    </>
  );
}
