"use client";

import Script from "next/script";
import { useState } from "react";
import { useI18n } from "@/lib/i18n/client";
import { ButtonLink } from "@/components/ui/button";
import { Callout } from "@/components/ui/misc";

type PaddleGlobal = {
  Environment: { set: (env: string) => void };
  Initialize: (opts: { token: string; checkout?: { settings?: { successUrl?: string } } }) => void;
};

/** Loads Paddle.js v2; with ?_ptxn in the URL it opens the checkout for that transaction itself. */
export function PaddleCheckout({
  transactionId,
  token,
  environment,
}: {
  transactionId: string | null;
  token: string;
  environment: "sandbox" | "production";
}) {
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  if (!transactionId || !token) {
    return (
      <Callout tone="warn" className="mt-4">
        {t("checkout.missing")}
      </Callout>
    );
  }
  return (
    <>
      <p className="mt-2 text-[14px] text-muted">{t("checkout.opening")}</p>
      {failed && (
        <Callout tone="danger" className="mt-4">
          {t("checkout.failed")}
        </Callout>
      )}
      <div className="mt-6">
        <ButtonLink href="/app/settings/billing" size="sm">
          {t("checkout.back")}
        </ButtonLink>
      </div>
      <Script
        src="https://cdn.paddle.com/paddle/v2/paddle.js"
        strategy="afterInteractive"
        onError={() => setFailed(true)}
        onLoad={() => {
          const paddle = (window as unknown as { Paddle?: PaddleGlobal }).Paddle;
          if (!paddle) {
            setFailed(true);
            return;
          }
          if (environment === "sandbox") paddle.Environment.set("sandbox");
          paddle.Initialize({
            token,
            checkout: { settings: { successUrl: `${window.location.origin}/app/settings/billing?checkout=success` } },
          });
        }}
      />
    </>
  );
}
