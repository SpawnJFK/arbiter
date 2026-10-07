import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { Webhooks } from "./webhooks";

export const metadata: Metadata = { title: "Webhooks" };

export default async function WebhooksPage() {
  const { items } = await withAuth((api) => api.webhooks(), "/app/settings/webhooks");
  return <Webhooks initial={items} />;
}
