"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/input";
import { Callout, EmptyState, Progress, Skeleton } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { ApiError, errorMessage } from "@/lib/api";
import { useI18n } from "@/lib/i18n/client";
import { LANGS } from "@/lib/langs";
import { STRING_PLATFORMS, stringsApi, type StringProject, type StringTier } from "@/lib/strings";

export function StringProjects() {
  const { t, f } = useI18n();
  const [items, setItems] = useState<StringProject[] | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems((await stringsApi.projects()).items);
    } catch (e) {
      setError({ code: e instanceof ApiError ? e.code : "error", message: errorMessage(e) });
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  if (error) {
    return error.code === "module_disabled" ? (
      <Card>
        <EmptyState title={t("app.strings.moduleDisabled")} description={t("app.strings.moduleDisabledHint")} />
      </Card>
    ) : (
      <Callout tone="danger" title={t("app.strings.loadFailed")}>
        {error.message}
      </Callout>
    );
  }
  const newButton = (
    <Button variant="primary" onClick={() => setOpen(true)}>
      <Icons.plus className="size-4" /> {t("app.strings.newProject")}
    </Button>
  );
  return (
    <>
      <div className="mb-3 flex justify-end">{newButton}</div>
      <Card>
        {items === null ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState title={t("app.strings.noProjects")} description={t("app.strings.noProjectsHint")} action={newButton} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.strings.project")}</Th>
                <Th>{t("app.strings.languages")}</Th>
                <Th className="text-right">{t("app.strings.keys")}</Th>
                <Th className="w-56">{t("app.strings.progress")}</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((p) => {
                const langs = p.stats?.languages ?? {};
                const targets = p.target_langs.map((l) => langs[l]?.progress ?? 0);
                const avg = targets.length ? Math.round(targets.reduce((a, b) => a + b, 0) / targets.length) : 0;
                return (
                  <Tr key={p.id}>
                    <Td>
                      <Link href={`/app/strings/${p.id}`} className="font-medium hover:text-accent hover:underline">
                        {p.name}
                      </Link>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {p.platforms.map((pl) => (
                          <Badge key={pl}>{t(`app.strings.platform.${pl}`)}</Badge>
                        ))}
                      </div>
                    </Td>
                    <Td className="text-muted">
                      <span className="font-mono text-[12.5px]">{p.base_lang}</span>
                      <Icons.send className="mx-1 inline size-3" aria-hidden="true" />
                      <span className="font-mono text-[12.5px]">{p.target_langs.join(", ")}</span>
                    </Td>
                    <Td className="tabular text-right">{f.num(p.stats?.keys ?? 0)}</Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        <Progress value={avg} className="flex-1" />
                        <span className="tabular w-9 text-right text-[12.5px] text-muted">{avg}%</span>
                      </div>
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
      <NewProjectDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function NewProjectDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, f } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState("");
  const [base, setBase] = useState("en");
  const [targets, setTargets] = useState<string[]>(["de", "fr"]);
  const [platforms, setPlatforms] = useState<string[]>(["web"]);
  const [tier, setTier] = useState<StringTier>("hybrid");
  const [busy, setBusy] = useState(false);

  function toggle(list: string[], v: string): string[] {
    return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const p = await stringsApi.createProject({
        name: name.trim(),
        base_lang: base,
        target_langs: targets.filter((x) => x !== base),
        platforms,
        tier,
      });
      toast.success(t("app.strings.projectCreated"));
      onClose();
      router.push(`/app/strings/${p.id}`);
    } catch (err) {
      toast.error(t("app.strings.couldNotCreate"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("app.strings.newProject")} size="lg">
      <form onSubmit={create} className="space-y-4">
        <Field label={t("app.strings.projectName")}>
          {(id) => <Input id={id} required value={name} onChange={(e) => setName(e.target.value)} autoFocus />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("app.strings.baseLanguage")} hint={t("app.strings.baseLanguageHint")}>
            {(id, d) => (
              <Select id={id} aria-describedby={d} value={base} onChange={(e) => setBase(e.target.value)}>
                {LANGS.map((l) => (
                  <option key={l} value={l}>
                    {f.langName(l)} ({l})
                  </option>
                ))}
              </Select>
            )}
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
        </div>
        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium">{t("app.strings.targetLanguages")}</legend>
          <div className="grid max-h-44 grid-cols-2 gap-x-3 gap-y-1 overflow-y-auto rounded-md border border-border p-2 sm:grid-cols-3">
            {LANGS.filter((l) => l !== base).map((l) => (
              <Checkbox key={l} checked={targets.includes(l)} onChange={() => setTargets(toggle(targets, l))} label={`${f.langName(l)} (${l})`} />
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium">{t("app.strings.platforms")}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {STRING_PLATFORMS.map((pl) => (
              <Checkbox key={pl} checked={platforms.includes(pl)} onChange={() => setPlatforms(toggle(platforms, pl))} label={t(`app.strings.platform.${pl}`)} />
            ))}
          </div>
        </fieldset>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            {t("app.strings.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!name.trim() || targets.filter((x) => x !== base).length === 0}>
            {t("app.strings.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
