"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { errorMessage } from "@/lib/api";
import { fieldErrors, startSession } from "@/lib/session-client";

export function RegisterForm() {
  const router = useRouter();
  const [form, setForm] = useState({ org_name: "", name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await startSession("register", form);
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
      <Field label="Company name" error={fields.org_name}>
        {(id, d) => <Input id={id} aria-describedby={d} required autoComplete="organization" value={form.org_name} onChange={set("org_name")} />}
      </Field>
      <Field label="Your name" error={fields.name}>
        {(id, d) => <Input id={id} aria-describedby={d} required autoComplete="name" value={form.name} onChange={set("name")} />}
      </Field>
      <Field label="Work email" error={fields.email}>
        {(id, d) => <Input id={id} aria-describedby={d} type="email" required autoComplete="email" value={form.email} onChange={set("email")} />}
      </Field>
      <Field label="Password" hint="At least 10 characters." error={fields.password}>
        {(id, d) => (
          <Input id={id} aria-describedby={d} type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={set("password")} />
        )}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        Create account
      </Button>
    </form>
  );
}
