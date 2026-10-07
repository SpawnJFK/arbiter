"use client";

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
  "job.delivered": "A job finished and the file is ready to download.",
  "job.failed": "A job stopped with an error.",
  "job.needs_attention": "Something needs a human decision (shows up under Exceptions).",
  "quote.expired": "A quote passed its valid-until time without a project.",
};

export function Webhooks({ initial }: { initial: Webhook[] }) {
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
      toast.error("Could not create webhook", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(w: Webhook) {
    try {
      await api.deleteWebhook(w.id);
      setHooks((xs) => xs.filter((x) => x.id !== w.id));
      toast.success("Webhook deleted");
      setDeleting(null);
    } catch (err) {
      toast.error("Could not delete", errorMessage(err));
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
          title="Webhooks"
          description="We POST a signed JSON event to your URL for each subscribed event."
          actions={
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Icons.plus className="size-4" /> Add endpoint
            </Button>
          }
        />
        {hooks.length === 0 ? (
          <EmptyState title="No endpoints" description="Add one to hear about deliveries and failures without polling." />
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
                  {w.active ? "Active" : "Disabled"}
                </Badge>
                <Button size="sm" variant="ghost" onClick={() => setDeleting(w)}>
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="Verifying signatures" />
        <CardBody className="space-y-2 text-[13.5px] text-muted">
          <p>
            Each request carries <code className="rounded bg-subtle px-1 font-mono text-[12.5px] text-fg">Arbiter-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code>.
            Compute HMAC-SHA256 of <code className="rounded bg-subtle px-1 font-mono text-[12.5px] text-fg">{"`${t}.${rawBody}`"}</code> with your
            endpoint secret and compare it to <code className="font-mono text-[12.5px] text-fg">v1</code> in constant time. Reject timestamps older than five minutes.
          </p>
        </CardBody>
      </Card>

      <Dialog open={open} onClose={close} title={secret ? "Copy the signing secret" : "Add endpoint"}>
        {secret ? (
          <div className="space-y-4">
            <Callout tone="warn" title="Shown only once">
              Use it to verify the Arbiter-Signature header. Delete and re-create the endpoint to rotate it.
            </Callout>
            <CopyField value={secret} label="Webhook signing secret" />
            <div className="flex justify-end">
              <Button variant="primary" onClick={close}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={create} className="space-y-4">
            <Field label="Endpoint URL" hint="HTTPS only.">
              {(id, d) => (
                <Input id={id} aria-describedby={d} type="url" required pattern="https://.*" placeholder="https://example.com/hooks/arbiter" value={url} onChange={(e) => setUrl(e.target.value)} />
              )}
            </Field>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-[13px] font-medium">Events</legend>
              {WEBHOOK_EVENTS.map((ev) => (
                <Checkbox
                  key={ev}
                  label={<span className="font-mono text-[12.5px]">{ev}</span>}
                  hint={EVENT_HELP[ev]}
                  checked={events.includes(ev)}
                  onChange={(e) => setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))}
                />
              ))}
            </fieldset>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" loading={busy} disabled={!url || events.length === 0}>
                Add endpoint
              </Button>
            </div>
          </form>
        )}
      </Dialog>

      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        size="sm"
        title="Delete this endpoint?"
        description="Events stop being sent to it immediately."
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => deleting && remove(deleting)}>
              Delete
            </Button>
          </>
        }
      />
    </div>
  );
}
