import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard } from "@/components/auth-card";
import { ResetForm } from "./reset-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("password.reset.title"), referrer: "no-referrer" };
}

export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { t } = await getI18n();
  const { token = "" } = await searchParams;
  return (
    <AuthCard
      title={t("password.reset.title")}
      description={t("password.reset.description")}
      footer={
        <Link href="/login" className="font-medium text-accent hover:underline">
          {t("password.backToSignIn")}
        </Link>
      }
    >
      <ResetForm token={token} />
    </AuthCard>
  );
}
