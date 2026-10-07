import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { Cockpit } from "./cockpit";

export const metadata: Metadata = { title: "Review cockpit" };

export default async function CockpitPage() {
  const me = await withAuth((api) => api.reviewerMe(), "/reviewer/cockpit");
  const pairs = me.pairs.filter((p) => p.status === "active").map(({ source_lang, target_lang }) => ({ source_lang, target_lang }));
  return <Cockpit pairs={pairs} />;
}
