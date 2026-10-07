"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { money } from "@/lib/format";

export function RunPayoutsButton() {
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const r = await api.runPayouts();
      toast.success(`${r.created} payout(s) created`, `Total ${money(r.total)}`);
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error("Payout run failed", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        Run payouts
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        title="Run payouts now?"
        description="Creates one payout per eligible reviewer. Safe to retry: the request carries an idempotency key."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={run} loading={busy}>
              Run payouts
            </Button>
          </>
        }
      />
    </>
  );
}
