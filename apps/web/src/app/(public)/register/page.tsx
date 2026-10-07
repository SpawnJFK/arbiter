import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard } from "@/components/auth-card";
import { RegisterForm } from "./register-form";

export const metadata: Metadata = { title: "Create a company account" };

export default function RegisterPage() {
  return (
    <AuthCard
      title="Create a company account"
      description="You will be the project manager for your organisation and can invite colleagues later."
      footer={
        <>
          Already have an account? <Link href="/login" className="font-medium text-accent hover:underline">Sign in</Link>
        </>
      }
    >
      <RegisterForm />
    </AuthCard>
  );
}
