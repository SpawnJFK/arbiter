"use client";

import { useEffect, useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { stringsApi, type HistoryItem, type StringKey } from "@/lib/strings";
import { StateBadge } from "./key-grid";
import { PlaceholderInput } from "./placeholder-input";
import type { WorkspaceCtx } from "./workspace";

const RTL = new Set(["ar", "he", "fa", "ur"]);

function sourceFormFor(form: string, source: Record<string, string>): string {
  if (form in source) return source[form];
  return source.other ?? Object.values(source)[0] ?? "";
}

/** Detail panel for one key: context for translators, the target editor (string, plural forms
 *  or array items) with placeholder chips, QA issues, actions and the version history. */
export function KeyEditor({
  ctx,
  item,
  lang,
  readOnly,
  onChange,
  onClose,
}: {
  ctx: WorkspaceCtx;
  item: StringKey;
  lang: string;
  readOnly: boolean;
  onChange: (k: StringKey) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const { project, branch } = ctx;
  const base = item.translations[project.base_lang];
  const tr = item.translations[lang];
  const sourceForms: Record<string, string> = base?.forms ?? { other: base?.value ?? "" };
  const targetForms =
    item.kind === "plural"
      ? (item.plural_forms?.[lang] ?? ["one", "other"])
      : item.kind === "array"
        ? Object.keys(sourceForms)
        : [];
  const [value, setValue] = useState(tr?.value ?? "");
  const [forms, setForms] = useState<Record<string, string>>(tr?.forms ?? {});
  const [meta, setMeta] = useState({
    description: item.description,
    screenshot_url: item.screenshot_url ?? "",
    max_length: item.max_length ? String(item.max_length) : "",
    tags: item.tags.join(", "),
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const dir = RTL.has(lang.split("-")[0]) ? "rtl" : "ltr";

  useEffect(() => {
    if (!showHistory) return;
    stringsApi
      .history(project.id, item.id, lang)
      .then((r) => setHistory(r.items))
      .catch(() => setHistory([]));
  }, [showHistory, project.id, item.id, lang, tr?.version]);

  async function run(label: string, fn: () => Promise<StringKey>, ok: string) {
    setBusy(label);
    try {
      const k = await fn();
      onChange(k);
      const next = k.translations[lang];
      setValue(next?.value ?? "");
      setForms(next?.forms ?? {});
      if (next?.blocked) toast.error(t("app.strings.editor.savedBlocked"));
      else toast.success(ok);
    } catch (e) {
      toast.error(t("app.strings.editor.saveFailed"), errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const body = item.kind === "string" ? { value } : { forms: Object.fromEntries(Object.entries(forms).filter(([, v]) => v !== "")) };
  const save = (state: "reviewed" | "approved") =>
    run(state, () => stringsApi.setTranslation(project.id, item.id, lang, { ...body, state }, branch.id), t("app.strings.editor.saved"));
  const suggest = () =>
    run("suggest", async () => (await stringsApi.suggest(project.id, item.id, lang, branch.id)).key, t("app.strings.editor.suggested"));
  const clear = () => run("clear", () => stringsApi.clearTranslation(project.id, item.id, lang, branch.id), t("app.strings.editor.cleared"));
  const saveMeta = () =>
    run(
      "meta",
      () =>
        stringsApi.updateKey(
          project.id,
          item.id,
          {
            description: meta.description,
            screenshot_url: meta.screenshot_url.trim() || null,
            max_length: meta.max_length ? Number(meta.max_length) : null,
            tags: meta.tags
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
          },
          branch.id,
        ),
      t("app.strings.editor.metaSaved"),
    );

  const empty = item.kind === "string" ? !value.trim() : Object.values(forms).every((v) => !v.trim());
  return (
    <Card className="w-full shrink-0 self-start p-4 lg:sticky lg:top-4 lg:w-[460px]">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="break-all font-mono text-[13px] font-medium text-fg">
            {item.namespace && <span className="text-muted">{item.namespace}:</span>}
            {item.name}
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge tone="info">{t(`app.strings.kind.${item.kind}`)}</Badge>
            <StateBadge state={tr?.state ?? "untranslated"} blocked={tr?.blocked} />
            {tr?.needs_review && <Badge tone="warn">{t("app.strings.state.needs_review")}</Badge>}
            {tr?.branch_local && <Badge tone="violet">{t("app.strings.grid.branchOnly")}</Badge>}
            {tr?.engine && <Badge>{tr.engine}</Badge>}
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label={t("app.strings.editor.close")}>
          {t("app.strings.editor.close")}
        </Button>
      </div>

      <section className="space-y-1.5" aria-label={t("app.strings.editor.sourceSection")}>
        <div className="text-[12px] font-medium text-muted">{t("app.strings.grid.source", { lang: project.base_lang })}</div>
        {item.kind === "string" ? (
          <p className="whitespace-pre-wrap rounded-md bg-subtle px-2.5 py-2 text-sm">{base?.value}</p>
        ) : (
          <dl className="space-y-1 rounded-md bg-subtle px-2.5 py-2 text-sm">
            {Object.entries(sourceForms).map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="w-12 shrink-0 font-mono text-[12px] text-muted">{k}</dt>
                <dd className="whitespace-pre-wrap">{v}</dd>
              </div>
            ))}
          </dl>
        )}
        {item.description && <p className="text-[12.5px] text-muted">{item.description}</p>}
        {item.screenshot_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={item.screenshot_url} alt={t("app.strings.editor.screenshotAlt", { key: item.name })} className="max-h-48 rounded-md border border-border object-contain" />
        )}
      </section>

      <section className="mt-4 space-y-2" aria-label={t("app.strings.editor.targetSection")}>
        <div className="text-[12px] font-medium text-muted">{t("app.strings.grid.target", { lang })}</div>
        {!item.translatable ? (
          <Callout tone="info">{t("app.strings.grid.notTranslatable")}</Callout>
        ) : item.kind === "string" ? (
          <PlaceholderInput
            value={value}
            onChange={setValue}
            source={base?.value ?? ""}
            placeholders={item.placeholders}
            maxLength={item.max_length}
            dir={dir}
            disabled={readOnly}
            label={t("app.strings.grid.target", { lang })}
          />
        ) : (
          targetForms.map((form) => (
            <div key={form}>
              <div className="mb-0.5 flex items-baseline justify-between text-[12px]">
                <span className="font-mono text-muted">{form}</span>
                <span className="truncate text-faint">{sourceFormFor(form, sourceForms)}</span>
              </div>
              <PlaceholderInput
                value={forms[form] ?? ""}
                onChange={(v) => setForms((cur) => ({ ...cur, [form]: v }))}
                source={sourceFormFor(form, sourceForms)}
                placeholders={item.placeholders}
                maxLength={item.max_length}
                dir={dir}
                disabled={readOnly}
                label={t("app.strings.editor.formLabel", { form })}
                optionalMissing={item.kind === "plural"}
              />
            </div>
          ))
        )}
        {tr?.qa && tr.qa.length > 0 && (
          <ul className="space-y-1 text-[12.5px]" aria-label={t("app.strings.editor.qaIssues")}>
            {tr.qa.map((i, n) => (
              <li key={n} className={i.blocking ? "text-danger" : "text-warn"}>
                <span className="font-mono">{i.code}</span>
                {i.form ? ` [${i.form}]` : ""}: {i.message}
              </li>
            ))}
          </ul>
        )}
        {item.translatable && (
          <div className="flex flex-wrap gap-2 pt-1">
            <Button variant="primary" size="sm" loading={busy === "reviewed"} disabled={readOnly || empty || busy !== null} onClick={() => save("reviewed")}>
              {t("app.strings.editor.save")}
            </Button>
            <Button size="sm" loading={busy === "approved"} disabled={readOnly || empty || busy !== null} onClick={() => save("approved")}>
              <Icons.check className="size-3.5" /> {t("app.strings.editor.approve")}
            </Button>
            <Button size="sm" loading={busy === "suggest"} disabled={readOnly || Boolean(tr && tr.state !== "untranslated") || busy !== null} onClick={suggest}>
              <Icons.sparkle className="size-3.5" /> {t("app.strings.editor.suggest")}
            </Button>
            <Button size="sm" variant="outline-danger" loading={busy === "clear"} disabled={readOnly || !tr || tr.state === "untranslated" || busy !== null} onClick={clear}>
              {t("app.strings.editor.clear")}
            </Button>
          </div>
        )}
      </section>

      <details className="mt-4 rounded-md border border-border px-3 py-2">
        <summary className="cursor-pointer text-[13px] font-medium">{t("app.strings.editor.contextSection")}</summary>
        <div className="mt-2 space-y-2">
          <Field label={t("app.strings.editor.description")} hint={t("app.strings.editor.descriptionHint")}>
            {(id, d) => <Textarea id={id} aria-describedby={d} rows={2} value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} disabled={readOnly} />}
          </Field>
          <Field label={t("app.strings.editor.screenshotUrl")}>
            {(id) => <Input id={id} type="url" value={meta.screenshot_url} onChange={(e) => setMeta({ ...meta, screenshot_url: e.target.value })} disabled={readOnly} />}
          </Field>
          <div className="grid grid-cols-[8rem_1fr] gap-2">
            <Field label={t("app.strings.editor.maxLength")}>
              {(id) => <Input id={id} type="number" min={1} value={meta.max_length} onChange={(e) => setMeta({ ...meta, max_length: e.target.value })} disabled={readOnly} />}
            </Field>
            <Field label={t("app.strings.editor.tags")} hint={t("app.strings.editor.tagsHint")}>
              {(id, d) => <Input id={id} aria-describedby={d} value={meta.tags} onChange={(e) => setMeta({ ...meta, tags: e.target.value })} disabled={readOnly} />}
            </Field>
          </div>
          <Button size="sm" loading={busy === "meta"} disabled={readOnly || busy !== null} onClick={saveMeta}>
            {t("app.strings.editor.saveContext")}
          </Button>
        </div>
      </details>

      <details className="mt-2 rounded-md border border-border px-3 py-2" onToggle={(e) => setShowHistory(e.currentTarget.open)}>
        <summary className="cursor-pointer text-[13px] font-medium">{t("app.strings.editor.history")}</summary>
        {history === null ? (
          <p className="mt-2 text-[12.5px] text-muted">{t("app.strings.editor.loading")}</p>
        ) : history.length === 0 ? (
          <p className="mt-2 text-[12.5px] text-muted">{t("app.strings.editor.noHistory")}</p>
        ) : (
          <ol className="mt-2 max-h-64 space-y-2 overflow-y-auto text-[12.5px]">
            {history.map((h) => (
              <li key={h.id} className="border-l-2 border-border pl-2">
                <div className="flex flex-wrap items-center gap-1.5 text-muted">
                  <Badge>{t(`app.strings.event.${h.event}`)}</Badge>
                  {h.lang && <span className="font-mono">{h.lang}</span>}
                  {h.version > 0 && <span>{t("app.strings.editor.version", { version: h.version })}</span>}
                  <span>{t(`app.strings.actor.${h.actor_type}`)}</span>
                  <Time iso={h.at} mode="relative" />
                </div>
                {(h.value || h.forms) && (
                  <div className="mt-0.5 whitespace-pre-wrap text-fg">{h.forms ? Object.entries(h.forms).map(([k, v]) => `${k}: ${v}`).join("\n") : h.value}</div>
                )}
              </li>
            ))}
          </ol>
        )}
      </details>
    </Card>
  );
}
