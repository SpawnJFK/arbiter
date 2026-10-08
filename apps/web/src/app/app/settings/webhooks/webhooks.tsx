"use client";

import { k } from "@/lib/i18n/core";
import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { CopyField } from "@/components/copy-field";
import { Icons } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input } from "@/components/ui/input";
import { Callout, EmptyState } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { WEBHOOK_EVENTS, type Webhook, type WebhookEvent } from "@/lib/types";

const EVENT_HELP: Record<WebhookEvent, string> = {
  "job.delivered": k("app.settings.webhooks.event.job_delivered"),
  "job.failed": k("app.settings.webhooks.event.job_failed"),
  "job.needs_attention": k("app.settings.webhooks.event.job_needs_attention"),
  "quote.expired": k("app.settings.webhooks.event.quote_expired"),
};

export function Webhooks({ initial }: { initial: Webhook[] }) {
  const { t } = useI18n();
  const toast = useToast();
  const [hooks, setHooks] = useState(initial);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<WebhookEvent[]>(["job.delivered", "job.needs_attention"]);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Webhook | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const w = await api.createWebhook({ url: url.trim(), events });
      setSecret(w.secret ?? null);
      const { secret: _s, ...rest } = w;
      void _s;
      setHooks((xs) => [...xs, rest]);
      setUrl("");
    } catch (err) {
      toast.error(t("app.settings.webhooks.webhooks.couldNotCreateWebhook"), errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(w: Webhook) {
    try {
      await api.deleteWebhook(w.id);
      setHooks((xs) => xs.filter((x) => x.id !== w.id));
      toast.success(t("app.settings.webhooks.webhooks.webhookDeleted"));
      setDeleting(null);
    } catch (err) {
      toast.error(t("app.settings.webhooks.webhooks.couldNotDelete"), errorMessage(err));
    }
  }

  const close = () => {
    setOpen(false);
    setSecret(null);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t("app.settings.webhooks.webhooks.webhooks")}
          description={t("app.settings.webhooks.webhooks.wePostASignedJson")}
          actions={
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Icons.plus className="size-4" /> {t("app.settings.webhooks.webhooks.addEndpoint")}
            </Button>
          }
        />
        {hooks.length === 0 ? (
          <EmptyState title={t("app.settings.webhooks.webhooks.noEndpoints")} description={t("app.settings.webhooks.webhooks.addOneToHearAbout")} />
        ) : (
          <ul className="divide-y divide-border">
            {hooks.map((w) => (
              <li key={w.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-[13px]">{w.url}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {w.events.map((e) => (
                      <Badge key={e}>{e}</Badge>
                    ))}
                  </div>
                </div>
                <Badge tone={w.active ? "ok" : "neutral"} dot>
                  {w.active ? t("app.settings.webhooks.webhooks.active") : t("app.settings.webhooks.webhooks.disabled")}
                </Badge>
                <Button size="sm" variant="ghost" onClick={() => setDeleting(w)}>
                  {t("app.settings.webhooks.webhooks.delete")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title={t("app.settings.webhooks.webhooks.verifyingSignatures")} />
        <CardBody className="space-y-2 text-[13.5px] text-muted">
          <p>
            {t("app.settings.webhooks.webhooks.eachRequestCarries")} <code className="rounded bg-subtle px-1 font-mono text-[12.5px] text-fg">{t("app.settings.webhooks.webhooks.arbiterSignatureTUnixV1")}</code>{t("app.settings.webhooks.webhooks.computeHmacSha256Of")} <code className="rounded bg-subtle px-1 font-mono text-[12.5px] text-fg">{t("app.settings.webhooks.webhooks.text")}</code> {t("app.settings.webhooks.webhooks.withYourEndpointSecretAnd")} <code className="font-mono text-[12.5px] text-fg">v1</code> {t("app.settings.webhooks.webhooks.inConstantTimeRejectTimestamps")}
          </p>
        </CardBody>
      </Card>

      <Dialog open={open} onClose={close} title={secret ? t("app.settings.webhooks.webhooks.copyTheSigningSecret") : t("app.settings.webhooks.webhooks.addEndpoint")}>
        {secret ? (
          <div className="space-y-4">
            <Callout tone="warn" title={t("app.settings.webhooks.webhooks.shownOnlyOnce")}>
              {t("app.settings.webhooks.webhooks.useItToVerifyThe")}
            </Callout>
            <CopyField value={secret} label={t("app.settings.webhooks.webhooks.webhookSigningSecret")} />
            <div className="flex justify-end">
              <Button variant="primary" onClick={close}>
                {t("app.settings.webhooks.webhooks.done")}
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={create} className="space-y-4">
            <Field label={t("app.settings.webhooks.webhooks.endpointUrl")} hint={t("app.settings.webhooks.webhooks.httpsOnly")}>
              {(id, d) => (
                <Input id={id} aria-describedby={d} type="url" required pattern="https://.*" placeholder={t("app.settings.webhooks.webhooks.httpsExampleComHooksArbiter")} value={url} onChange={(e) => setUrl(e.target.value)} />
              )}
            </Field>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-[13px] font-medium">{t("app.settings.webhooks.webhooks.events")}</legend>
              {WEBHOOK_EVENTS.map((ev) => (
                <Checkbox
                  key={ev}
                  label={<span className="font-mono text-[12.5px]">{ev}</span>}
                  hint={t(EVENT_HELP[ev])}
                  checked={events.includes(ev)}
                  onChange={(e) => setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))}
                />
              ))}
            </fieldset>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close}>
                {t("app.settings.webhooks.webhooks.cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={!url || events.length === 0}>
                {t("app.settings.webhooks.webhooks.addEndpoint")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        size="sm"
        title={t("app.settings.webhooks.webhooks.deleteThisEndpoint")}
        description={t("app.settings.webhooks.webhooks.eventsStopBeingSentTo")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              {t("app.settings.webhooks.webhooks.cancel")}
            </Button>
            <Button variant="danger" onClick={() => deleting && remove(deleting)}>
              {t("app.settings.webhooks.webhooks.delete")}
            </Button>
          </>
        }
      />
    </div>
  );
}
