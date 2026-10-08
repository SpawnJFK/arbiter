"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";

/** Banner for a job whose workflow has client_review and that is waiting for the approval. */
export function ClientApproval({ jobId }: { jobId: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function approve() {
    setBusy(true);
    try {
      await api.clientApprove(jobId);
      toast.success(t("app.jobs.detail.clientApproval.approved"), t("app.jobs.detail.clientApproval.theJobIsBeingMerged"));
      router.refresh();
    } catch (e) {
      toast.error(t("app.jobs.detail.clientApproval.couldNotApprove"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div role="region" aria-label={t("app.jobs.detail.clientApproval.clientApproval")} className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-warn/40 bg-warn-subtle px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-warn">{t("app.jobs.detail.clientApproval.waitingForClientApproval")}</div>
        <p className="text-[13.5px] text-fg/90">
          {t("app.jobs.detail.clientApproval.everySegmentHasBeenReviewed")}
        </p>
      </div>
      <Button variant="primary" onClick={approve} loading={busy}>
        {t("app.jobs.detail.clientApproval.approveAndDeliver")}
      </Button>
    </div>
  );
}
