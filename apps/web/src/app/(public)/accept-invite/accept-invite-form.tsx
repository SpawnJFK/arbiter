"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { errorMessage } from "@/lib/api";
import { startSession } from "@/lib/session-client";

/** Sets the password of an invited team member (one-time token from the invite link). */
export function AcceptInviteForm() {
  const { t } = useI18n();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!token) return <Callout tone="danger">{t("platform.invite.missingToken")}</Callout>;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError(t("platform.invite.mismatch"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await startSession("invite", { token, password, name: name.trim() || undefined });
      router.replace(redirect);
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      {error && <Callout tone="danger">{error}</Callout>}
      <Field label={t("platform.invite.name")} hint={t("platform.common.optional")}>
        {(id, d) => <Input id={id} aria-describedby={d} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <Field label={t("platform.invite.password")} hint={t("platform.invite.passwordHint")}>
        {(id, d) => (
          <Input id={id} aria-describedby={d} type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        )}
      </Field>
      <Field label={t("platform.invite.confirm")}>
        {(id) => <Input id={id} type="password" required minLength={8} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        {t("platform.invite.submit")}
      </Button>
    </form>
  );
}
