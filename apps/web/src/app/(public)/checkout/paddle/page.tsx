import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PaddleCheckout } from "./paddle-checkout";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("checkout.metaTitle") };
}

/**
 * Paddle's hosted checkout opens on this page: the API creates a transaction whose checkout URL
 * is this page plus ?_ptxn=<transaction id>, and Paddle.js opens the overlay for it (D-072).
 * The page's domain must be approved in Paddle. Token and environment are public values.
 */
export default async function PaddleCheckoutPage({ searchParams }: { searchParams: Promise<{ _ptxn?: string }> }) {
  const { _ptxn } = await searchParams;
  const { t } = await getI18n();
  return (
    <div className="mx-auto max-w-xl px-4 py-16 md:px-6">
      <h1 className="text-xl font-semibold tracking-tight">{t("checkout.title")}</h1>
      <PaddleCheckout
        transactionId={_ptxn ?? null}
        token={process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN ?? ""}
        environment={process.env.NEXT_PUBLIC_PADDLE_ENVIRONMENT === "production" ? "production" : "sandbox"}
      />
    </div>
  );
}
