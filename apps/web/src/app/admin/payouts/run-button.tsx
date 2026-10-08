"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";

export function RunPayoutsButton() {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const r = await api.runPayouts();
      toast.success(t("admin.payouts.runButton.payoutSCreated", { created: r.created }), t("admin.payouts.runButton.total", { total: f.money(r.total) }));
      setOpen(false);
      router.refresh();
    } catch (e) {
      toast.error(t("admin.payouts.runButton.payoutRunFailed"), errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        {t("admin.payouts.runButton.runPayouts")}
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        size="sm"
        title={t("admin.payouts.runButton.runPayoutsNow")}
        description={t("admin.payouts.runButton.createsOnePayoutPerEligible")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("admin.payouts.runButton.cancel")}
            </Button>
            <Button variant="primary" onClick={run} loading={busy}>
              {t("admin.payouts.runButton.runPayouts")}
            </Button>
          </>
        }
      />
    </>
  );
}
