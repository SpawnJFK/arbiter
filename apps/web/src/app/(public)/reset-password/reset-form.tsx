"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { ApiError, errorMessage } from "@/lib/api";
import { startSession } from "@/lib/session-client";

const MIN_LENGTH = 8;

export function ResetForm({ token }: { token: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);

  // The token lives in the URL only until the page has it; drop it from history.
  useEffect(() => {
    if (token && window.location.search.includes("token=")) {
      const url = new URL(window.location.href);
      url.searchParams.delete("token");
      window.history.replaceState(null, "", url.pathname + url.search);
    }
  }, [token]);

  if (!token || expired) {
    return (
      <div className="space-y-4">
        <Callout tone="warn">{t("password.reset.invalidLink")}</Callout>
        <Link href="/forgot-password" className="block text-center text-[14px] font-medium text-accent hover:underline">
          {t("password.reset.requestNew")}
        </Link>
      </div>
    );
  }

  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        if (password.length < MIN_LENGTH) return setError(t("password.reset.tooShort", { min: MIN_LENGTH }));
        if (password !== confirm) return setError(t("password.reset.mismatch"));
        setBusy(true);
        try {
          const { redirect } = await startSession("reset", { token, password });
          router.replace(redirect);
          router.refresh();
        } catch (err) {
          if (err instanceof ApiError && err.code === "invalid_token") setExpired(true);
          else setError(errorMessage(err));
          setBusy(false);
        }
      }}
    >
      {error && <Callout tone="danger">{error}</Callout>}
      <Field label={t("password.reset.newPassword")} hint={t("password.reset.hint", { min: MIN_LENGTH })}>
        {(id, d) => (
          <Input
            id={id}
            aria-describedby={d}
            type="password"
            autoComplete="new-password"
            minLength={MIN_LENGTH}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <Field label={t("password.reset.confirmPassword")}>
        {(id) => (
          <Input id={id} type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        )}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        {t("password.reset.submit")}
      </Button>
    </form>
  );
}
