import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { WorkflowPipeline } from "@/components/workflow-pipeline";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { TIER_LABEL } from "@/lib/format";
import { withAuth } from "@/lib/server-api";
import type { Workflow } from "@/lib/types";

export const metadata: Metadata = { title: "Workflows" };

export default async function WorkflowsPage() {
  const { items } = await withAuth((api) => api.workflows({ limit: 200 }), "/app/workflows");
  const custom = items.filter((w) => !w.preset);
  const presets = items.filter((w) => w.preset);
  return (
    <>
      <PageHeader
        title="Workflows"
        description="The steps a job runs through. A job freezes its workflow when it is created, so editing a template never changes running work."
        actions={
          <ButtonLink href="/app/workflows/new" variant="primary">
            <Icons.plus className="size-4" /> New workflow
          </ButtonLink>
        }
      />
      <h2 className="mb-2 text-[13px] font-semibold text-muted">Your workflows</h2>
      {custom.length === 0 ? (
        <Card className="mb-6 px-4 py-6 text-center text-[13.5px] text-muted">No custom workflows yet. Start from a preset below or create one.</Card>
      ) : (
        <div className="mb-6 grid gap-3 lg:grid-cols-2">{custom.map((w) => <WorkflowCard key={w.id} w={w} />)}</div>
      )}
      <h2 className="mb-2 text-[13px] font-semibold text-muted">Presets</h2>
      <div className="grid gap-3 lg:grid-cols-2">{presets.map((w) => <WorkflowCard key={w.id} w={w} />)}</div>
    </>
  );
}

function WorkflowCard({ w }: { w: Workflow }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/app/workflows/${w.id}`} className="font-semibold hover:text-accent hover:underline">
          {w.name}
        </Link>
        <Badge tone={w.tier === "hybrid" || w.tier === "full" ? "violet" : "accent"}>{TIER_LABEL[w.tier]}</Badge>
        {w.is_default && <Badge tone="ok">Org default</Badge>}
        {w.preset && <Badge>Preset</Badge>}
        {w.available === false && <Badge tone="warn">Not available</Badge>}
      </div>
      {w.description && <p className="mt-1 text-[13px] text-muted">{w.description}</p>}
      <WorkflowPipeline steps={w.steps} compact className="mt-3" />
      {w.blocked_reason && <p className="mt-2 text-[12.5px] text-warn">{w.blocked_reason}</p>}
    </Card>
  );
}
