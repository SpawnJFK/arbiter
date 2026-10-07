"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";

export function CancelJobButton({ jobId }: { jobId: string }) {
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function cancel() {
    setBusy(true);
    try {
      await api.cancelJob(jobId);
      toast.success("Job cancelled");
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error("Could not cancel", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="outline-danger" onClick={() => setOpen(true)}>
        Cancel job
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        title="Cancel this job?"
        description="This stops all remaining work on this language and releases any segment a reviewer is holding. It cannot be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Keep running
            </Button>
            <Button variant="danger" onClick={cancel} loading={busy}>
              Cancel job
            </Button>
          </>
        }
      />
    </>
  );
}
