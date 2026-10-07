"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Field, Input, Label, Select } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { langName } from "@/lib/format";
import { CONTENT_TYPES, LANGS } from "@/lib/langs";
import { fieldErrors, startSession } from "@/lib/session-client";
import type { LangPair } from "@/lib/types";

export function ApplyForm() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "", country: "" });
  const [pairs, setPairs] = useState<LangPair[]>([{ source_lang: "en", target_lang: "" }]);
  const [domains, setDomains] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const validPairs = pairs.filter((p) => p.source_lang && p.target_lang && p.source_lang !== p.target_lang);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (validPairs.length === 0) return setError("Add at least one language pair with different source and target.");
    if (domains.length === 0) return setError("Pick at least one domain.");
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await startSession("apply", { ...form, country: form.country.toUpperCase(), pairs: validPairs, domains });
      router.replace(redirect);
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setFields(fieldErrors(err));
      setBusy(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      {error && <Callout tone="danger">{error}</Callout>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name" error={fields.name}>
          {(id, d) => <Input id={id} aria-describedby={d} required autoComplete="name" value={form.name} onChange={set("name")} />}
        </Field>
        <Field label="Country" hint="Two-letter code, e.g. DE" error={fields.country}>
          {(id, d) => (
            <Input
              id={id}
              aria-describedby={d}
              required
              maxLength={2}
              pattern="[A-Za-z]{2}"
              autoComplete="country"
              value={form.country}
              onChange={set("country")}
            />
          )}
        </Field>
      </div>
      <Field label="Email" error={fields.email}>
        {(id, d) => <Input id={id} aria-describedby={d} type="email" required autoComplete="email" value={form.email} onChange={set("email")} />}
      </Field>
      <Field label="Password" hint="At least 10 characters." error={fields.password}>
        {(id, d) => (
          <Input id={id} aria-describedby={d} type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={set("password")} />
        )}
      </Field>

      <fieldset>
        <legend className="mb-1 text-[13px] font-medium">Language pairs</legend>
        <p className="mb-2 text-[12.5px] text-muted">Only pairs you work in professionally. Each one has its own test.</p>
        <div className="space-y-2">
          {pairs.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <Select
                aria-label={`Pair ${i + 1} source language`}
                value={p.source_lang}
                onChange={(e) => setPairs(pairs.map((x, j) => (j === i ? { ...x, source_lang: e.target.value } : x)))}
                className="flex-1"
              >
                {LANGS.map((l) => (
                  <option key={l} value={l}>
                    {langName(l)} ({l})
                  </option>
                ))}
              </Select>
              <Icons.arrowRight className="size-4 shrink-0 text-faint" />
              <Select
                aria-label={`Pair ${i + 1} target language`}
                value={p.target_lang}
                onChange={(e) => setPairs(pairs.map((x, j) => (j === i ? { ...x, target_lang: e.target.value } : x)))}
                className="flex-1"
              >
                <option value="">Target…</option>
                {LANGS.filter((l) => l !== p.source_lang).map((l) => (
                  <option key={l} value={l}>
                    {langName(l)} ({l})
                  </option>
                ))}
              </Select>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Remove pair ${i + 1}`}
                disabled={pairs.length === 1}
                onClick={() => setPairs(pairs.filter((_, j) => j !== i))}
              >
                ×
              </Button>
            </div>
          ))}
        </div>
        <Button size="sm" variant="ghost" className="mt-2" onClick={() => setPairs([...pairs, { source_lang: "en", target_lang: "" }])}>
          <Icons.plus className="size-3.5" /> Add pair
        </Button>
      </fieldset>

      <fieldset>
        <Label>Domains</Label>
        <div className="flex flex-wrap gap-1.5">
          {CONTENT_TYPES.map((c) => {
            const on = domains.includes(c.value);
            return (
              <button
                key={c.value}
                type="button"
                aria-pressed={on}
                onClick={() => setDomains(on ? domains.filter((d) => d !== c.value) : [...domains, c.value])}
                className={cn(
                  "h-7 rounded-full border px-3 text-[13px] transition-colors",
                  on ? "border-accent bg-accent-subtle text-accent" : "border-border-strong text-muted hover:bg-hover",
                )}
              >
                {c.label}
              </button>
            );
          })}
        </div>
      </fieldset>

      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        Apply
      </Button>
    </form>
  );
}
