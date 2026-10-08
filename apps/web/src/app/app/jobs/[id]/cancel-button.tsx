"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";

export function CancelJobButton({ jobId }: { jobId: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function cancel() {
    setBusy(true);
    try {
      await api.cancelJob(jobId);
      toast.success(t("app.jobs.detail.cancelButton.jobCancelled"));
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error(t("app.jobs.detail.cancelButton.couldNotCancel"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="outline-danger" onClick={() => setOpen(true)}>
        {t("app.jobs.detail.cancelButton.cancelJob")}
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        title={t("app.jobs.detail.cancelButton.cancelThisJob")}
        description={t("app.jobs.detail.cancelButton.thisStopsAllRemainingWork")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("app.jobs.detail.cancelButton.keepRunning")}
            </Button>
            <Button variant="danger" onClick={cancel} loading={busy}>
              {t("app.jobs.detail.cancelButton.cancelJob")}
            </Button>
          </>
        }
      />
    </>
  );
}
