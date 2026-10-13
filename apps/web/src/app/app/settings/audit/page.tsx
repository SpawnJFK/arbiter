import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge, type Tone } from "@/components/ui/badge";
import { AnchorButton, Button, ButtonLink } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { Icons } from "@/components/icons";
import { withAuth } from "@/lib/server-api";
import type { AuditFilters } from "@/lib/platform-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("platform.audit.metaTitle") };
}

const PAGE = 50;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

function nextDay(d: string): string {
  const x = new Date(`${d}T00:00:00Z`);
  x.setUTCDate(x.getUTCDate() + 1);
  return x.toISOString();
}

const TONE: Record<string, Tone> = { created: "ok", deleted: "danger", revoked: "danger", deactivated: "warn", cancelled: "warn" };

function actionTone(action: string): Tone {
  const verb = action.split(".").pop() ?? "";
  return TONE[verb] ?? (action.startsWith("auth.") ? "info" : "neutral");
}

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ actor?: string; action?: string; since?: string; until?: string; offset?: string }>;
}) {
  const sp = await searchParams;
  const { t } = await getI18n();
  const offset = Math.max(0, Number.parseInt(sp.offset ?? "0", 10) || 0);
  const filters: AuditFilters = {
    actor: sp.actor?.trim() || undefined,
    action: sp.action?.trim() || undefined,
    since: sp.since && DAY.test(sp.since) ? `${sp.since}T00:00:00Z` : undefined,
    until: sp.until && DAY.test(sp.until) ? nextDay(sp.until) : undefined,
  };
  const [page, exportUrl] = await withAuth(
    async (api) => [await api.auditLog({ ...filters, offset, limit: PAGE }), api.auditLogExportUrl(filters)] as const,
    "/app/settings/audit",
  );
  const qs = (o: number) => {
    const p = new URLSearchParams();
    for (const k of ["actor", "action", "since", "until"] as const) if (sp[k]) p.set(k, sp[k]!);
    if (o) p.set("offset", String(o));
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  const filtered = Boolean(filters.actor || filters.action || filters.since || filters.until);

  return (
    <Card>
      <CardHeader
        title={t("platform.audit.title")}
        description={t("platform.audit.description")}
        actions={
          <AnchorButton href={exportUrl} download>
            <Icons.download className="size-4" /> {t("platform.audit.exportCsv")}
          </AnchorButton>
        }
      />
      <form method="get" className="grid gap-2 border-b border-border px-4 py-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto_auto_auto]">
        <Input name="actor" defaultValue={sp.actor ?? ""} placeholder={t("platform.audit.actorPlaceholder")} aria-label={t("platform.audit.actor")} />
        <Input name="action" defaultValue={sp.action ?? ""} placeholder={t("platform.audit.actionPlaceholder")} aria-label={t("platform.audit.action")} />
        <Input name="since" type="date" defaultValue={sp.since ?? ""} aria-label={t("platform.audit.since")} title={t("platform.audit.since")} />
        <Input name="until" type="date" defaultValue={sp.until ?? ""} aria-label={t("platform.audit.until")} title={t("platform.audit.until")} />
        <div className="flex gap-2">
          <Button type="submit" variant="primary">
            {t("platform.audit.filter")}
          </Button>
          {filtered && (
            <Link href="/app/settings/audit" className="inline-flex h-8.5 items-center px-2 text-[13px] text-muted hover:text-fg">
              {t("platform.common.reset")}
            </Link>
          )}
        </div>
      </form>
      {page.items.length === 0 ? (
        <EmptyState title={t("platform.audit.empty")} description={filtered ? t("platform.audit.emptyFiltered") : undefined} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("platform.audit.when")}</Th>
              <Th className="hidden sm:table-cell">{t("platform.audit.actor")}</Th>
              <Th>{t("platform.audit.action")}</Th>
              <Th className="hidden md:table-cell">{t("platform.audit.target")}</Th>
              <Th className="hidden lg:table-cell">{t("platform.audit.ip")}</Th>
            </tr>
          </THead>
          <TBody>
            {page.items.map((e) => {
              const hasData = Object.keys(e.data ?? {}).length > 0;
              return (
                <Tr key={e.id} className="align-top">
                  <Td className="text-muted sm:whitespace-nowrap">
                    <Time iso={e.at} />
                    <div className="max-w-[150px] truncate text-[12px] text-faint sm:hidden">
                      {e.actor.label || t(`platform.audit.actorType.${e.actor.type}`)}
                    </div>
                  </Td>
                  <Td className="hidden max-w-[200px] sm:table-cell">
                    <div className="truncate">{e.actor.label || t(`platform.audit.actorType.${e.actor.type}`)}</div>
                    {e.actor.type === "api_key" && <div className="text-[12px] text-faint">{t("platform.audit.actorType.api_key")}</div>}
                  </Td>
                  <Td className="max-w-[320px]">
                    <Badge tone={actionTone(e.action)}>
                      <span className="font-mono">{e.action}</span>
                    </Badge>
                    {hasData && (
                      <details className="mt-1 text-[12px]">
                        <summary className="cursor-pointer text-muted hover:text-fg">{t("platform.audit.details")}</summary>
                        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-subtle p-2 font-mono text-[11.5px] text-fg">
                          {JSON.stringify(e.data, null, 2)}
                        </pre>
                      </details>
                    )}
                  </Td>
                  <Td className="hidden max-w-[220px] md:table-cell">
                    <div className="text-[12.5px] text-muted">{e.target.type}</div>
                    <div className="truncate font-mono text-[12px] text-faint">{e.target.id}</div>
                  </Td>
                  <Td className="hidden lg:table-cell">
                    <div className="font-mono text-[12px] text-muted">{e.ip || "–"}</div>
                    <div className="max-w-[200px] truncate text-[11.5px] text-faint" title={e.user_agent}>
                      {e.user_agent}
                    </div>
                  </Td>
                </Tr>
              );
            })}
          </TBody>
        </Table>
      )}
      {(offset > 0 || page.next_offset !== null) && (
        <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
          {offset > 0 ? (
            <ButtonLink size="sm" variant="ghost" href={`/app/settings/audit${qs(Math.max(0, offset - PAGE))}`}>
              {t("platform.common.previous")}
            </ButtonLink>
          ) : (
            <span />
          )}
          {page.next_offset !== null && (
            <ButtonLink size="sm" variant="ghost" href={`/app/settings/audit${qs(page.next_offset)}`}>
              {t("platform.common.next")}
            </ButtonLink>
          )}
        </div>
      )}
    </Card>
  );
}
