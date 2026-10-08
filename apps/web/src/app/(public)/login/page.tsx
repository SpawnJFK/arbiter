import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AuthCard } from "@/components/auth-card";
import { LoginForm } from "./login-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("login.signIn") };
}

export default async function LoginPage() {
  const { t } = await getI18n();
  return (
    <AuthCard
      title={t("login.signIn")}
      description={t("login.customersReviewersAndOperatorsAll")}
      footer={
        <>
          {t("login.newCompany")} <Link href="/register" className="font-medium text-accent hover:underline">{t("login.createAnAccount")}</Link> ·{" "}
          <Link href="/reviewers/apply" className="font-medium text-accent hover:underline">{t("login.applyAsAReviewer")}</Link>
        </>
      }
    >
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthCard>
  );
}
