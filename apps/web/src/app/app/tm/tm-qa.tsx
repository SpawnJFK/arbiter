"use client";

import { useI18n } from "@/lib/i18n/client";
import { useEffect, useState } from "react";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { LANGS } from "@/lib/langs";
import type { Glossary } from "@/lib/types";
import type { TmQa } from "@/lib/types-workbench";

export function TmQaView() {
  const { t } = useI18n();
  const toast = useToast();
  const [sl, setSl] = useState("en");
  const [tl, setTl] = useState("de");
  const [glossary, setGlossary] = useState("");
  const [data, setData] = useState<TmQa | null>(null);
  const [busy, setBusy] = useState(false);
  const [glossaries, setGlossaries] = useState<Glossary[]>([]);

  useEffect(() => {
    let live = true;
    api
      .glossaries({ limit: 200 })
      .then((res) => live && setGlossaries(res.items))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setData(await api.tmQa({ source_lang: sl, target_lang: tl, glossary_id: glossary.trim() || undefined }));
    } catch (err) {
      toast.error(t("app.tm.qa.failed"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t("app.tm.qa.title")} description={t("app.tm.qa.description")} />
        <form onSubmit={run} className="flex flex-wrap items-center gap-2 px-4 pb-4">
          <Select aria-label={t("app.tm.tmScreen.sourceLanguage")} className="w-24" value={sl} onChange={(e) => setSl(e.target.value)}>
            {LANGS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
          <Select aria-label={t("app.tm.tmScreen.targetLanguage")} className="w-24" value={tl} onChange={(e) => setTl(e.target.value)}>
            {LANGS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </Select>
          <Select aria-label={t("app.tm.qa.glossary")} className="w-56" value={glossary} onChange={(e) => setGlossary(e.target.value)}>
            <option value="">{t("app.tm.qa.noGlossary")}</option>
            {glossaries.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
          <Button type="submit" variant="primary" loading={busy}>
            {t("app.tm.qa.run")}
          </Button>
        </form>
      </Card>
      {data && (
        <>
          <Card>
            <CardHeader title={t("app.tm.qa.inconsistent", { n: data.inconsistent.length })} />
            {data.inconsistent.length === 0 ? (
              <EmptyState title={t("app.tm.qa.noInconsistent")} />
            ) : (
              <ul className="divide-y divide-border">
                {data.inconsistent.map((g, i) => (
                  <li key={i} className="px-4 py-3 text-[13.5px]">
                    <TaggedText value={g.source_tagged} className="font-medium" />
                    <ul className="mt-1.5 space-y-1">
                      {g.variants.map((v, k) => (
                        <li key={k} className="flex items-start gap-2">
                          <Badge tone="neutral" className="tabular">
                            {v.entry_ids.length}x
                          </Badge>
                          <TaggedText value={v.target_tagged} />
                          <span className="ml-auto text-[12px] text-faint">{v.origins.map((o) => t.enumLabel(o)).join(", ")}</span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {glossary.trim() && (
            <Card>
              <CardHeader title={t("app.tm.qa.violations", { n: data.glossary_violations.length })} />
              {data.glossary_violations.length === 0 ? (
                <EmptyState title={t("app.tm.qa.noViolations")} />
              ) : (
                <ul className="divide-y divide-border">
                  {data.glossary_violations.map((v) => (
                    <li key={v.entry_id} className="grid gap-2 px-4 py-3 text-[13.5px] sm:grid-cols-2">
                      <TaggedText value={v.source_tagged} />
                      <div>
                        <TaggedText value={v.target_tagged} />
                        {v.violations.map((x, k) => (
                          <p key={k} className="text-[12px] text-danger">
                            {x.message}
                          </p>
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
