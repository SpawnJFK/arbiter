"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";

/** Banner for a job whose workflow has client_review and that is waiting for the approval. */
export function ClientApproval({ jobId }: { jobId: string }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function approve() {
    setBusy(true);
    try {
      await api.clientApprove(jobId);
      toast.success("Approved", "The job is being merged and delivered.");
      router.refresh();
    } catch (e) {
      toast.error("Could not approve", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div role="region" aria-label="Client approval" className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-warn/40 bg-warn-subtle px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-warn">Waiting for client approval</div>
        <p className="text-[13.5px] text-fg/90">
          Every segment has been reviewed. Check the translation below, then approve to merge and deliver. Download the evidence pack if the client needs it for sign-off.
        </p>
      </div>
      <Button variant="primary" onClick={approve} loading={busy}>
        Approve and deliver
      </Button>
    </div>
  );
}
