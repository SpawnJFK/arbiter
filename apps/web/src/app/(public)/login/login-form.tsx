"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { ApiError, errorMessage } from "@/lib/api";
import { IS_MOCK } from "@/lib/config";
import { startSession } from "@/lib/session-client";

// sso_error codes set by /api/sso/start and /api/sso/callback.
const SSO_ERRORS: Record<string, string> = {
  not_found: k("platform.ssoLogin.errorNotSetUp"),
  email_required: k("platform.ssoLogin.errorEmailRequired"),
  idp_error: k("platform.ssoLogin.errorIdp"),
  forbidden: k("platform.ssoLogin.errorDomain"),
  conflict: k("platform.ssoLogin.errorOtherOrg"),
  not_in_demo: k("platform.ssoLogin.errorDemo"),
};

const DEMO = [
  { email: "pm@demo.test", label: k("login.loginForm.pm") },
  { email: "client@demo.test", label: k("login.loginForm.client") },
  { email: "reviewer@demo.test", label: k("login.loginForm.reviewer") },
  { email: "admin@demo.test", label: k("login.loginForm.admin") },
];

export function LoginForm() {
  const { t } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const ssoError = params.get("sso_error");
  const [error, setError] = useState<string | null>(
    ssoError ? t(SSO_ERRORS[ssoError] ?? k("platform.ssoLogin.errorGeneric")) : null,
  );

  function sso(e: string) {
    if (!e.includes("@")) {
      setError(t("platform.ssoLogin.errorEmailRequired"));
      return;
    }
    setBusy(true);
    const qs = new URLSearchParams({ email: e });
    const next = params.get("next");
    if (next) qs.set("next", next);
    // Full navigation: a route handler that redirects to the IdP, another site.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/api/sso/start?${qs}`);
  }

  async function login(e: string, p: string) {
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await startSession("login", { email: e, password: p }, params.get("next"));
      router.replace(redirect);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "sso_required") {
        sso(e); // the organization signs in through its identity provider only
        return;
      }
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void login(email, password);
      }}
    >
      {error && <Callout tone="danger">{error}</Callout>}
      <Field label={t("login.loginForm.email")}>
        {(id) => (
          <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        )}
      </Field>
      <Field label={t("login.loginForm.password")}>
        {(id) => (
          <Input
            id={id}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <div className="-mt-1 text-right">
        <Link href="/forgot-password" className="text-[13px] font-medium text-accent hover:underline">
          {t("login.loginForm.forgotPassword")}
        </Link>
      </div>
      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        {t("login.loginForm.signIn")}
      </Button>
      <div className="flex items-center gap-3 text-[12px] text-faint" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />
        {t("platform.ssoLogin.or")}
        <span className="h-px flex-1 bg-border" />
      </div>
      <Button className="w-full" disabled={busy} onClick={() => sso(email.trim())}>
        {t("platform.ssoLogin.continue")}
      </Button>
      {IS_MOCK && (
        <div className="border-t border-border pt-4">
          <p className="mb-2 text-[12.5px] text-muted">{t("login.loginForm.demoModeSignInAs")}</p>
          <div className="grid grid-cols-4 gap-1.5">
            {DEMO.map((d) => (
              <Button key={d.email} size="sm" disabled={busy} onClick={() => void login(d.email, "demo")}>
                {t(d.label)}
              </Button>
            ))}
          </div>
        </div>
      )}
    </form>
  );
}
