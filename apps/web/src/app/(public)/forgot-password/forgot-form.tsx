"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { errorMessage } from "@/lib/api";
import { requestPasswordReset } from "@/lib/session-client";

export function ForgotForm() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  if (sentTo) {
    return (
      <div className="space-y-4" role="status" aria-live="polite">
        <Callout tone="ok">{t("password.forgot.sent", { email: sentTo })}</Callout>
        <p className="text-[13.5px] text-muted">{t("password.forgot.sentHint")}</p>
        <Button className="w-full" onClick={() => setSentTo(null)}>
          {t("password.forgot.tryAnother")}
        </Button>
      </div>
    );
  }

  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await requestPasswordReset(email);
          setSentTo(email.trim());
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      {error && <Callout tone="danger">{error}</Callout>}
      <Field label={t("login.loginForm.email")}>
        {(id) => <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        {t("password.forgot.submit")}
      </Button>
    </form>
  );
}
