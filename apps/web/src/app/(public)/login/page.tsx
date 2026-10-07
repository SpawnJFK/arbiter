import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AuthCard } from "@/components/auth-card";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <AuthCard
      title="Sign in"
      description="Customers, reviewers and operators all sign in here."
      footer={
        <>
          New company? <Link href="/register" className="font-medium text-accent hover:underline">Create an account</Link> ·{" "}
          <Link href="/reviewers/apply" className="font-medium text-accent hover:underline">Apply as a reviewer</Link>
        </>
      }
    >
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthCard>
  );
}
