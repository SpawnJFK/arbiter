import type { Metadata } from "next";
import { getMe, withAuth } from "@/lib/server-api";
import { PolicyForm } from "./policy-form";

export const metadata: Metadata = { title: "Policies" };

export default async function PoliciesPage() {
  const [{ user }, org] = await Promise.all([getMe(), withAuth((api) => api.org(), "/app/settings")]);
  return <PolicyForm org={org} canEdit={user.role === "pm"} />;
}
