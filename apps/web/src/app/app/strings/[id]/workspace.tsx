"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/input";
import { Callout, PageHeader, Skeleton } from "@/components/ui/misc";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { stringsApi, type StringBranch, type StringFormat, type StringProject } from "@/lib/strings";
import { Branches } from "./branches";
import { KeyGrid } from "./key-grid";
import { Releases } from "./releases";
import { ProjectSettings } from "./settings-panel";
import { Transfer } from "./transfer";

const TABS = ["keys", "transfer", "branches", "releases", "settings"] as const;
type Tab = (typeof TABS)[number];

export interface WorkspaceCtx {
  project: StringProject;
  branch: StringBranch;
  branches: StringBranch[];
  formats: StringFormat[];
  reloadProject: () => Promise<void>;
  reloadBranches: () => Promise<void>;
}

export function StringWorkspace({ projectId }: { projectId: string }) {
  const { t } = useI18n();
  const [project, setProject] = useState<StringProject | null>(null);
  const [branches, setBranches] = useState<StringBranch[]>([]);
  const [formats, setFormats] = useState<StringFormat[]>([]);
  const [branchId, setBranchId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("keys");
  const [error, setError] = useState<string | null>(null);

  const reloadProject = useCallback(async () => {
    setProject(await stringsApi.project(projectId));
  }, [projectId]);
  const reloadBranches = useCallback(async () => {
    const list = (await stringsApi.branches(projectId)).items;
    setBranches(list);
    setBranchId((cur) => (cur && list.some((b) => b.id === cur) ? cur : (list.find((b) => b.is_main)?.id ?? null)));
  }, [projectId]);

  useEffect(() => {
    (async () => {
      try {
        const [p, fm] = await Promise.all([stringsApi.project(projectId), stringsApi.formats()]);
        setProject(p);
        setFormats(fm.items);
        await reloadBranches();
      } catch (e) {
        setError(errorMessage(e));
      }
    })();
  }, [projectId, reloadBranches]);

  if (error) {
    return (
      <Callout tone="danger" title={t("app.strings.loadFailed")}>
        {error}
      </Callout>
    );
  }
  const branch = branches.find((b) => b.id === branchId);
  if (!project || !branch) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96" />
      </div>
    );
  }
  const ctx: WorkspaceCtx = { project, branch, branches, formats, reloadProject, reloadBranches };
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/strings" className="hover:text-fg">
            {t("app.strings.title")}
          </Link>
        }
        title={project.name}
        description={t("app.strings.projectSummary", {
          base: project.base_lang,
          targets: project.target_langs.join(", "),
          keys: project.stats?.keys ?? 0,
        })}
        actions={
          <label className="flex items-center gap-2 text-[13px] text-muted">
            {t("app.strings.branch")}
            <Select value={branch.id} onChange={(e) => setBranchId(e.target.value)} className="w-48">
              {branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                  {b.merged_at ? ` (${t("app.strings.merged")})` : ""}
                </option>
              ))}
            </Select>
          </label>
        }
      />
      {!branch.is_main && (
        <Callout tone={branch.merged_at ? "warn" : "info"} className="mb-4">
          {branch.merged_at ? t("app.strings.branchMergedReadOnly") : t("app.strings.branchNotice", { name: branch.name })}
        </Callout>
      )}
      <div role="tablist" aria-label={t("app.strings.sections")} className="mb-4 flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((x) => (
          <button
            key={x}
            role="tab"
            type="button"
            aria-selected={tab === x}
            onClick={() => setTab(x)}
            className={cn(
              "-mb-px inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-[13.5px] transition-colors",
              tab === x ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            {t(`app.strings.tab.${x}`)}
            {x === "branches" && branches.length > 1 && <Badge>{branches.length - 1}</Badge>}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "keys" && <KeyGrid ctx={ctx} />}
        {tab === "transfer" && <Transfer ctx={ctx} />}
        {tab === "branches" && <Branches ctx={ctx} onOpen={(id) => { setBranchId(id); setTab("keys"); }} />}
        {tab === "releases" && <Releases ctx={ctx} />}
        {tab === "settings" && <ProjectSettings ctx={ctx} />}
      </div>
    </>
  );
}
