import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard } from "@/components/auth-card";
import { RegisterForm } from "./register-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("register.createACompanyAccount") };
}

export default async function RegisterPage() {
  const { t } = await getI18n();
  return (
    <AuthCard
      title={t("register.createACompanyAccount")}
      description={t("register.youWillBeTheProject")}
      footer={
        <>
          {t("register.alreadyHaveAnAccount")} <Link href="/login" className="font-medium text-accent hover:underline">{t("register.signIn")}</Link>
        </>
      }
    >
      <RegisterForm />
    </AuthCard>
  );
}
