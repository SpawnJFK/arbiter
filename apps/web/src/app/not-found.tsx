import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";

export default function NotFound() {
  return (
    <main id="main" className="flex min-h-dvh items-center justify-center">
      <EmptyState
        title="Not found"
        description="This page does not exist, or you do not have access to it."
        action={<ButtonLink href="/">Go home</ButtonLink>}
      />
    </main>
  );
}
