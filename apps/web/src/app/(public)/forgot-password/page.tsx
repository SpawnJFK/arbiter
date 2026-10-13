import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard } from "@/components/auth-card";
import { ForgotForm } from "./forgot-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("password.forgot.title") };
}

export default async function ForgotPasswordPage() {
  const { t } = await getI18n();
  return (
    <AuthCard
      title={t("password.forgot.title")}
      description={t("password.forgot.description")}
      footer={
        <Link href="/login" className="font-medium text-accent hover:underline">
          {t("password.backToSignIn")}
        </Link>
      }
    >
      <ForgotForm />
    </AuthCard>
  );
}
