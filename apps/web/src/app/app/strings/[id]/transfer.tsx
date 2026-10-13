"use client";

import { useState } from "react";
import { Icons } from "@/components/icons";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { stringsApi, type PushResult } from "@/lib/strings";
import type { WorkspaceCtx } from "./workspace";

/** Import (push) and export (pull) of resource files, with a format picker. */
export function Transfer({ ctx }: { ctx: WorkspaceCtx }) {
  const { t, f } = useI18n();
  const toast = useToast();
  const { project, branch, formats } = ctx;
  const langs = [project.base_lang, ...project.target_langs];
  const readOnly = Boolean(branch.merged_at);

  const [file, setFile] = useState<File | null>(null);
  const [inFormat, setInFormat] = useState("");
  const [inLang, setInLang] = useState(project.base_lang);
  const [namespace, setNamespace] = useState("");
  const [createKeys, setCreateKeys] = useState(true);
  const [archiveMissing, setArchiveMissing] = useState(false);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PushResult | null>(null);

  const [outFormat, setOutFormat] = useState(project.settings.default_format || "json");
  const [outLang, setOutLang] = useState(project.target_langs[0] ?? project.base_lang);
  const [minState, setMinState] = useState("machine");
  const [fallback, setFallback] = useState(false);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await stringsApi.push(project.id, file, {
        format: inFormat || undefined,
        lang: inLang,
        branch: branch.id,
        namespace,
        create_keys: inLang === project.base_lang ? createKeys : undefined,
        archive_missing: inLang === project.base_lang ? archiveMissing : undefined,
        tag: tag.trim() || undefined,
      });
      setResult(r);
      toast.success(t("app.strings.transfer.imported"));
      void ctx.reloadProject();
    } catch (err) {
      toast.error(t("app.strings.transfer.importFailed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const outSpec = formats.find((x) => x.name === outFormat);
  const href = stringsApi.pullUrl(project.id, {
    format: outFormat,
    lang: outSpec?.multilingual ? undefined : outLang,
    branch: branch.id,
    min_state: minState,
    fallback: fallback ? "true" : undefined,
  });

  const apiUrl = project.ota_base.split("/ota/")[0];
  const ciConfig = JSON.stringify(
    {
      apiUrl,
      projectId: project.id,
      tokenEnv: "ARBITER_TOKEN",
      files: [{ path: `locales/{lang}.${outSpec?.extension ?? "json"}`, format: outFormat }],
    },
    null,
    2,
  );
  const ciCommands = [
    "node cli/arbiter-strings.mjs push",
    "node cli/arbiter-strings.mjs pull --min-state reviewed",
    "node cli/arbiter-strings.mjs release --label 1.0.0",
  ].join("\n");

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title={t("app.strings.transfer.importTitle")} description={t("app.strings.transfer.importHint")} />
        <CardBody>
          <form onSubmit={upload} className="space-y-3">
            <Field label={t("app.strings.transfer.file")}>
              {(id) => <Input id={id} type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={readOnly} />}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("app.strings.transfer.format")}>
                {(id) => (
                  <Select id={id} value={inFormat} onChange={(e) => setInFormat(e.target.value)}>
                    <option value="">{t("app.strings.transfer.detect")}</option>
                    {formats.map((x) => (
                      <option key={x.name} value={x.name}>
                        {x.label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={t("app.strings.transfer.language")}>
                {(id) => (
                  <Select id={id} value={inLang} onChange={(e) => setInLang(e.target.value)}>
                    {langs.map((l) => (
                      <option key={l} value={l}>
                        {f.langName(l)} ({l}){l === project.base_lang ? ` ${t("app.strings.transfer.baseMark")}` : ""}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={t("app.strings.grid.namespace")} hint={t("app.strings.transfer.namespaceHint")}>
                {(id, d) => <Input id={id} aria-describedby={d} value={namespace} onChange={(e) => setNamespace(e.target.value)} />}
              </Field>
              <Field label={t("app.strings.grid.tag")} hint={t("app.strings.transfer.tagHint")}>
                {(id, d) => <Input id={id} aria-describedby={d} value={tag} onChange={(e) => setTag(e.target.value)} />}
              </Field>
            </div>
            {inLang === project.base_lang ? (
              <div className="space-y-1.5">
                <Checkbox checked={createKeys} onChange={(e) => setCreateKeys(e.target.checked)} label={t("app.strings.transfer.createKeys")} />
                <Checkbox
                  checked={archiveMissing}
                  onChange={(e) => setArchiveMissing(e.target.checked)}
                  label={t("app.strings.transfer.archiveMissing")}
                  hint={t("app.strings.transfer.archiveMissingHint")}
                />
              </div>
            ) : (
              <p className="text-[12.5px] text-muted">{t("app.strings.transfer.targetNote")}</p>
            )}
            <Button type="submit" variant="primary" loading={busy} disabled={!file || readOnly}>
              <Icons.upload className="size-4" /> {t("app.strings.transfer.import")}
            </Button>
          </form>
          {result && (
            <Callout tone={result.blocked ? "warn" : "ok"} className="mt-3" title={t("app.strings.transfer.resultTitle", { format: result.format, lang: result.lang })}>
              {t("app.strings.transfer.result", {
                created: result.created,
                updated: result.updated,
                unchanged: result.unchanged,
                archived: result.archived,
                skipped: result.skipped,
                blocked: result.blocked,
              })}
              {result.warnings.length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-[12.5px]">
                  {result.warnings.slice(0, 10).map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </Callout>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("app.strings.transfer.exportTitle")} description={t("app.strings.transfer.exportHint")} />
        <CardBody className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("app.strings.transfer.format")}>
              {(id) => (
                <Select id={id} value={outFormat} onChange={(e) => setOutFormat(e.target.value)}>
                  {formats.map((x) => (
                    <option key={x.name} value={x.name}>
                      {x.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("app.strings.transfer.language")} hint={outSpec?.multilingual ? t("app.strings.transfer.allLanguages") : undefined}>
              {(id, d) => (
                <Select id={id} aria-describedby={d} value={outLang} onChange={(e) => setOutLang(e.target.value)} disabled={outSpec?.multilingual}>
                  {langs.map((l) => (
                    <option key={l} value={l}>
                      {f.langName(l)} ({l})
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("app.strings.transfer.minState")}>
              {(id) => (
                <Select id={id} value={minState} onChange={(e) => setMinState(e.target.value)}>
                  {(["machine", "reviewed", "approved"] as const).map((x) => (
                    <option key={x} value={x}>
                      {t(`app.strings.state.${x}`)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
          <Checkbox checked={fallback} onChange={(e) => setFallback(e.target.checked)} label={t("app.strings.transfer.fallback")} hint={t("app.strings.transfer.fallbackHint")} />
          <AnchorButton href={href} variant="primary">
            <Icons.download className="size-4" /> {t("app.strings.transfer.download")}
          </AnchorButton>
          <p className="text-[12.5px] text-muted">{t("app.strings.transfer.blockedNote")}</p>
        </CardBody>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title={t("app.strings.transfer.ciTitle")} description={t("app.strings.transfer.ciHint")} />
        <CardBody className="space-y-2">
          <pre className="overflow-x-auto rounded-md bg-subtle p-3 font-mono text-[12.5px] text-fg">{ciConfig}</pre>
          <pre className="overflow-x-auto rounded-md bg-subtle p-3 font-mono text-[12.5px] text-fg">{ciCommands}</pre>
        </CardBody>
      </Card>
    </div>
  );
}
