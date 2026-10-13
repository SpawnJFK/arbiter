"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { stringsApi, type StringTier } from "@/lib/strings";
import type { WorkspaceCtx } from "./workspace";

const STYLES = ["auto", "icu", "printf", "rails", "mustache", "none"] as const;

/** Project settings: languages, tier, human review, what ships in releases, placeholders. */
export function ProjectSettings({ ctx }: { ctx: WorkspaceCtx }) {
  const { t } = useI18n();
  const toast = useToast();
  const { project, formats } = ctx;
  const s = project.settings;
  const [name, setName] = useState(project.name);
  const [targets, setTargets] = useState(project.target_langs.join(", "));
  const [tier, setTier] = useState<StringTier>(project.tier);
  const [humanReview, setHumanReview] = useState(s.human_review);
  const [minState, setMinState] = useState(s.release_min_state);
  const [fallback, setFallback] = useState(s.fallback_to_base);
  const [style, setStyle] = useState(s.placeholder_style);
  const [defaultFormat, setDefaultFormat] = useState(s.default_format);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await stringsApi.updateProject(project.id, {
        name: name.trim(),
        target_langs: targets
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        tier,
        settings: {
          human_review: humanReview,
          release_min_state: minState,
          fallback_to_base: fallback,
          placeholder_style: style,
          default_format: defaultFormat,
        },
      });
      await ctx.reloadProject();
      toast.success(t("app.strings.settings.saved"));
    } catch (err) {
      toast.error(t("app.strings.settings.failed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title={t("app.strings.tab.settings")} description={t("app.strings.settings.hint", { id: project.public_id })} />
      <CardBody>
        <form onSubmit={save} className="grid max-w-3xl gap-4 sm:grid-cols-2">
          <Field label={t("app.strings.projectName")}>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required />}</Field>
          <Field label={t("app.strings.targetLanguages")} hint={t("app.strings.settings.targetsHint")}>
            {(id, d) => <Input id={id} aria-describedby={d} value={targets} onChange={(e) => setTargets(e.target.value)} className="font-mono" />}
          </Field>
          <Field label={t("app.strings.tier")} hint={t("app.strings.tierHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={tier} onChange={(e) => setTier(e.target.value as StringTier)}>
                {(["auto", "ai_review", "hybrid", "full"] as const).map((x) => (
                  <option key={x} value={x}>
                    {t(`tier.${x}.label`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("app.strings.settings.minState")} hint={t("app.strings.settings.minStateHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={minState} onChange={(e) => setMinState(e.target.value as typeof minState)}>
                {(["machine", "reviewed", "approved"] as const).map((x) => (
                  <option key={x} value={x}>
                    {t(`app.strings.state.${x}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("app.strings.settings.placeholderStyle")} hint={t("app.strings.settings.placeholderStyleHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={style} onChange={(e) => setStyle(e.target.value)}>
                {STYLES.map((x) => (
                  <option key={x} value={x}>
                    {t(`app.strings.settings.style.${x}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("app.strings.settings.defaultFormat")}>
            {(id) => (
              <Select id={id} value={defaultFormat} onChange={(e) => setDefaultFormat(e.target.value)}>
                {formats.map((x) => (
                  <option key={x.name} value={x.name}>
                    {x.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="space-y-2 sm:col-span-2">
            <Checkbox checked={humanReview} onChange={(e) => setHumanReview(e.target.checked)} label={t("app.strings.settings.humanReview")} hint={t("app.strings.settings.humanReviewHint")} />
            <Checkbox checked={fallback} onChange={(e) => setFallback(e.target.checked)} label={t("app.strings.settings.fallback")} hint={t("app.strings.settings.fallbackHint")} />
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" variant="primary" loading={busy}>
              {t("app.strings.settings.save")}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
