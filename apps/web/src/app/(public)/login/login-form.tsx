"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/misc";
import { errorMessage } from "@/lib/api";
import { IS_MOCK } from "@/lib/config";
import { startSession } from "@/lib/session-client";

const DEMO = [
  { email: "pm@demo.test", label: "PM" },
  { email: "client@demo.test", label: "Client" },
  { email: "reviewer@demo.test", label: "Reviewer" },
  { email: "admin@demo.test", label: "Admin" },
];

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function login(e: string, p: string) {
    setBusy(true);
    setError(null);
    try {
      const { redirect } = await startSession("login", { email: e, password: p }, params.get("next"));
      router.replace(redirect);
      router.refresh();
    } catch (err) {
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
      <Field label="Email">
        {(id) => (
          <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        )}
      </Field>
      <Field label="Password">
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
      <Button type="submit" variant="primary" className="w-full" loading={busy}>
        Sign in
      </Button>
      {IS_MOCK && (
        <div className="border-t border-border pt-4">
          <p className="mb-2 text-[12.5px] text-muted">Demo mode: sign in as</p>
          <div className="grid grid-cols-4 gap-1.5">
            {DEMO.map((d) => (
              <Button key={d.email} size="sm" disabled={busy} onClick={() => void login(d.email, "demo")}>
                {d.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </form>
  );
}
