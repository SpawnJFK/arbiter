"use client";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main id="main" className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        title="Something went wrong"
        description={error.message || "The request failed. Try again in a moment."}
        action={<Button onClick={reset}>Try again</Button>}
      />
    </main>
  );
}
