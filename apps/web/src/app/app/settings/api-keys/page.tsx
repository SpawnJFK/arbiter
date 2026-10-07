import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { ApiKeys } from "./api-keys";

export const metadata: Metadata = { title: "API keys" };

export default async function ApiKeysPage() {
  const { items } = await withAuth((api) => api.apiKeys(), "/app/settings/api-keys");
  return <ApiKeys initial={items} />;
}
