"use client";

import { useCallback, useEffect, useState } from "react";
import { Icons } from "@/components/icons";
import { CopyField } from "@/components/copy-field";
import { Badge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input } from "@/components/ui/input";
import { Callout, EmptyState, Mono, Skeleton } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { stringsApi, type StringRelease } from "@/lib/strings";
import type { WorkspaceCtx } from "./workspace";

/** Releases: build per-language bundles, publish them over the air, copy the OTA URLs. */
export function Releases({ ctx }: { ctx: WorkspaceCtx }) {
  const { t, f } = useI18n();
  const toast = useToast();
  const { project, branch, formats } = ctx;
  const [items, setItems] = useState<StringRelease[] | null>(null);
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [extra, setExtra] = useState<string[]>([]);
  const [publish, setPublish] = useState(true);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await stringsApi.releases(project.id)).items);
    } catch (e) {
      toast.error(t("app.strings.loadFailed"), errorMessage(e));
      setItems([]);
    }
  }, [project.id, toast, t]);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await stringsApi.createRelease(project.id, { branch: branch.id, version_label: label.trim() || undefined, formats: extra, publish });
      toast.success(r.status === "published" ? t("app.strings.releases.published", { label: r.version_label }) : t("app.strings.releases.drafted", { label: r.version_label }));
      setOpen(false);
      setLabel("");
      void load();
    } catch (err) {
      toast.error(t("app.strings.releases.failed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function doPublish(r: StringRelease) {
    try {
      await stringsApi.publishRelease(project.id, r.id);
      toast.success(t("app.strings.releases.published", { label: r.version_label }));
      void load();
    } catch (err) {
      toast.error(t("app.strings.releases.failed"), errorMessage(err));
    }
  }

  async function newToken() {
    try {
      setToken((await stringsApi.distributionToken(project.id)).token);
      void ctx.reloadProject();
    } catch (err) {
      toast.error(t("app.strings.releases.tokenFailed"), errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t("app.strings.releases.title")}
          description={t("app.strings.releases.hint")}
          actions={
            <Button variant="primary" onClick={() => setOpen(true)} disabled={Boolean(branch.merged_at)}>
              <Icons.send className="size-4" /> {t("app.strings.releases.new")}
            </Button>
          }
        />
        <CardBody className="space-y-2">
          <div className="text-[12.5px] text-muted">{t("app.strings.releases.latestUrl")}</div>
          <CopyField value={`${project.ota_base}/latest/${project.target_langs[0] ?? project.base_lang}.json`} label={t("app.strings.releases.latestUrl")} />
          <div className="flex flex-wrap items-center gap-2 pt-1 text-[12.5px] text-muted">
            {project.settings.private ? <Badge tone="warn">{t("app.strings.releases.private")}</Badge> : <Badge tone="ok">{t("app.strings.releases.public")}</Badge>}
            <span>{project.settings.private ? t("app.strings.releases.privateHint") : t("app.strings.releases.publicHint")}</span>
            <Button size="sm" onClick={newToken}>
              <Icons.key className="size-3.5" /> {project.has_distribution_token ? t("app.strings.releases.rotateToken") : t("app.strings.releases.makePrivate")}
            </Button>
          </div>
          {token && (
            <Callout tone="warn" title={t("app.strings.releases.tokenOnce")}>
              <CopyField value={token} label={t("app.strings.releases.token")} />
            </Callout>
          )}
        </CardBody>
      </Card>

      {items === null ? (
        <Skeleton className="h-40" />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState title={t("app.strings.releases.none")} description={t("app.strings.releases.noneHint")} />
        </Card>
      ) : (
        items.map((r) => (
          <Card key={r.id}>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <span className="font-mono">{r.version_label}</span>
                  <Badge tone={r.status === "published" ? "ok" : "neutral"}>{t(`app.strings.releases.status.${r.status}`)}</Badge>
                </span>
              }
              description={t("app.strings.releases.summary", { keys: r.key_count, langs: r.langs.length })}
              actions={
                r.status === "draft" ? (
                  <Button size="sm" variant="primary" onClick={() => doPublish(r)}>
                    {t("app.strings.releases.publish")}
                  </Button>
                ) : (
                  <span className="text-[12.5px] text-muted">
                    <Time iso={r.published_at} mode="relative" />
                  </span>
                )
              }
            />
            <CardBody className="space-y-2">
              <div className="text-[12.5px] text-muted">
                {t("app.strings.releases.hash")} <Mono>{r.content_hash.slice(0, 16)}</Mono>
              </div>
              {r.langs.map((lang) => (
                <div key={lang} className="grid items-center gap-2 sm:grid-cols-[9rem_1fr_auto]">
                  <span className="text-[13px]">
                    {f.langName(lang)} <Mono>{lang}</Mono>
                  </span>
                  {r.ota ? <CopyField value={r.ota.langs[lang]?.versioned ?? ""} label={t("app.strings.releases.otaUrl", { lang })} /> : <span className="text-[12.5px] text-muted">{t("app.strings.releases.draftNoUrl")}</span>}
                  <div className="flex gap-1">
                    {Object.keys(r.files[lang] ?? {}).map((fmt) => (
                      <AnchorButton key={fmt} size="sm" href={stringsApi.releaseFileUrl(project.id, r.id, lang, fmt)}>
                        {fmt}
                      </AnchorButton>
                    ))}
                  </div>
                </div>
              ))}
              {r.files._all && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {Object.keys(r.files._all).map((fmt) => (
                    <AnchorButton key={fmt} size="sm" href={stringsApi.releaseFileUrl(project.id, r.id, "_all", fmt)}>
                      <Icons.download className="size-3.5" /> {fmt}
                    </AnchorButton>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        ))
      )}

      <Dialog open={open} onClose={() => setOpen(false)} title={t("app.strings.releases.new")} size="md">
        <form onSubmit={create} className="space-y-3">
          <Field label={t("app.strings.releases.label")} hint={t("app.strings.releases.labelHint")}>
            {(id, d) => <Input id={id} aria-describedby={d} value={label} onChange={(e) => setLabel(e.target.value)} className="font-mono" />}
          </Field>
          <fieldset>
            <legend className="mb-1.5 text-[13px] font-medium">{t("app.strings.releases.formats")}</legend>
            <p className="mb-1.5 text-[12.5px] text-muted">{t("app.strings.releases.formatsHint")}</p>
            <div className="grid grid-cols-2 gap-1">
              {formats
                .filter((x) => !x.bilingual && x.name !== "pot")
                .map((x) => (
                  <Checkbox key={x.name} checked={extra.includes(x.name)} onChange={() => setExtra(extra.includes(x.name) ? extra.filter((y) => y !== x.name) : [...extra, x.name])} label={x.label} />
                ))}
            </div>
          </fieldset>
          <Checkbox checked={publish} onChange={(e) => setPublish(e.target.checked)} label={t("app.strings.releases.publishNow")} hint={t("app.strings.releases.publishHint")} />
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("app.strings.cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={busy}>
              {t("app.strings.releases.build")}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
