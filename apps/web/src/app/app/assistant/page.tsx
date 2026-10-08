import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { AssistantChat } from "./chat";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.assistant.metaTitle") };
}

export default async function AssistantPage({ searchParams }: { searchParams: Promise<{ thread?: string }> }) {
  const { thread: threadId } = await searchParams;
  const [threads, thread] = await withAuth(
    async (api) => {
      const list = await api.threads();
      const id = threadId && list.items.some((item) => item.id === threadId) ? threadId : undefined;
      return [list.items, id ? await api.thread(id) : null] as const;
    },
    "/app/assistant",
  );
  // No key: the chat keeps its local state when the URL gains ?thread= after the first message.
  return <AssistantChat threads={threads} thread={thread} />;
}
