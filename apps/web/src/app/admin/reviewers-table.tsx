"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useState } from "react";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { contentTypeLabel } from "@/lib/langs";
import { REVIEWER_LEVELS, type ReviewerProfile } from "@/lib/types";


export function ReviewersTable({ initial, status, statuses }: { initial: ReviewerProfile[]; status: string; statuses: string[] }) {
  const { f, t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);

  async function update(r: ReviewerProfile, body: { status: string; level?: string }) {
    setBusy(r.id);
    try {
      const updated = await api.setReviewerStatus(r.id, body);
      setRows((xs) => xs.map((x) => (x.id === r.id ? { ...x, ...updated } : x)));
      toast.success(t("admin.reviewersTable.statusUpdated", { name: r.name ?? r.id, status: t.enumLabel(updated.status) }), body.level !== undefined ? t("admin.reviewersTable.levelSet", { level: t.enumLabel(body.level) }) : undefined);
    } catch (e) {
      toast.error(t("admin.reviewersTable.updateFailed"), errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap gap-1 border-b border-border px-3 py-2">
        {["", ...statuses].map((s) => (
          <Link
            key={s || "all"}
            href={s ? `/admin?status=${s}` : "/admin"}
            aria-current={status === s ? "page" : undefined}
            className={cn(
              "rounded-md px-2.5 py-1 text-[13px]",
              status === s ? "bg-hover font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg",
            )}
          >
            {s ? t.enumLabel(s) : t("admin.reviewersTable.all")}
          </Link>
        ))}
      </div>
      {rows.length === 0 ? (
        <EmptyState title={t("admin.reviewersTable.noReviewers")} description={status ? t("admin.reviewersTable.nobodyIsRightNow", { status: status }) : undefined} />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>{t("admin.reviewersTable.reviewer")}</Th>
              <Th>{t("admin.reviewersTable.pairs")}</Th>
              <Th className="hidden lg:table-cell">{t("admin.reviewersTable.domains")}</Th>
              <Th className="text-right">{t("admin.reviewersTable.score")}</Th>
              <Th>{t("admin.reviewersTable.status")}</Th>
              <Th>{t("admin.reviewersTable.level")}</Th>
              <Th className="hidden xl:table-cell text-right">{t("admin.reviewersTable.balance")}</Th>
              <Th className="text-right">
                <span className="sr-only">{t("admin.reviewersTable.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {rows.map((r) => (
              <Tr key={r.id}>
                <Td>
                  <div className="font-medium">{r.name ?? r.id}</div>
                  <div className="text-[12px] text-faint">
                    {r.email ?? r.id}
                    {r.country ? t("admin.reviewersTable.text2", { country: r.country }) : ""}
                  </div>
                </Td>
                <Td>
                  <div className="flex flex-col gap-0.5">
                    {r.pairs.map((p) => (
                      <span key={`${p.source_lang}-${p.target_lang}`} className="whitespace-nowrap font-mono text-[12px]">
                        {p.source_lang}→{p.target_lang} <span className="font-sans text-faint">{p.status}</span>
                      </span>
                    ))}
                  </div>
                </Td>
                <Td className="hidden text-[13px] text-muted lg:table-cell">{r.domains.map((d) => contentTypeLabel(t, d)).join(", ")}</Td>
                <Td className="tabular text-right">{r.score === null ? "–" : r.score.toFixed(0)}</Td>
                <Td>
                  <StatusBadge status={r.status} />
                  {!r.tax_info_complete && r.status === "active" && <div className="mt-1 text-[11.5px] text-warn">{t("admin.reviewersTable.noTaxInfo")}</div>}
                </Td>
                <Td>
                  <Select
                    aria-label={t("admin.reviewersTable.levelFor", { value: r.name ?? r.id })}
                    value={String(r.level)}
                    disabled={busy === r.id}
                    onChange={(e) => update(r, { status: r.status, level: e.target.value })}
                    className="w-36"
                  >
                    {REVIEWER_LEVELS.map((l) => (
                      <option key={l} value={l}>
                        {t.enumLabel(l)}
                      </option>
                    ))}
                  </Select>
                </Td>
                <Td className="tabular hidden text-right xl:table-cell">{f.money(r.balance)}</Td>
                <Td className="text-right">
                  <div className="flex justify-end gap-1">
                    {r.status !== "active" && (
                      <Button size="sm" variant="primary" disabled={busy === r.id} onClick={() => update(r, { status: "active", level: r.level === "candidate" ? "reviewer" : String(r.level) })}>
                        {r.status === "suspended" ? t("admin.reviewersTable.reinstate") : t("admin.reviewersTable.approve")}
                      </Button>
                    )}
                    {r.status === "active" && (
                      <Button size="sm" variant="outline-danger" disabled={busy === r.id} onClick={() => update(r, { status: "suspended" })}>
                        {t("admin.reviewersTable.suspend")}
                      </Button>
                    )}
                    {r.status !== "banned" && (
                      <Button size="sm" variant="ghost" disabled={busy === r.id} onClick={() => update(r, { status: "banned" })}>
                        {t("admin.reviewersTable.ban")}
                      </Button>
                    )}
                  </div>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}
