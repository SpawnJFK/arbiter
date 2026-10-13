import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AuthCard } from "@/components/auth-card";
import { AcceptInviteForm } from "./accept-invite-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("platform.invite.title") };
}

export default async function AcceptInvitePage() {
  const { t } = await getI18n();
  return (
    <AuthCard
      title={t("platform.invite.title")}
      description={t("platform.invite.description")}
      footer={
        <>
          {t("platform.invite.haveAccount")}{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            {t("login.signIn")}
          </Link>
        </>
      }
    >
      <Suspense>
        <AcceptInviteForm />
      </Suspense>
    </AuthCard>
  );
}
