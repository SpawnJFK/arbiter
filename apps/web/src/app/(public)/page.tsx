import { Icons } from "@/components/icons";
import { TaggedText } from "@/components/tagged-text";
import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { TIER_BLURB, TIER_LABEL } from "@/lib/format";

export default function Landing() {
  return (
    <>
      <section className="mx-auto grid max-w-6xl gap-10 px-4 pb-14 pt-14 md:grid-cols-[1.05fr_1fr] md:px-6 md:pt-20">
        <div>
          <p className="mb-3 text-[13px] font-medium text-accent">AI-native translation for businesses</p>
          <h1 className="text-[34px] font-semibold leading-[1.1] tracking-tight text-fg md:text-[44px]">
            Ship machine translation only where it has earned it.
          </h1>
          <p className="mt-4 max-w-xl text-[16px] leading-relaxed text-muted">
            Arbiter scores every segment, lets a panel of AI agents vote on the uncertain ones, and sends the rest to a vetted
            human reviewer. You see the price and expected automation before you commit, and you get the evidence for every
            decision afterwards.
          </p>
          <div className="mt-7 flex flex-wrap gap-2">
            <ButtonLink href="/register" variant="primary">
              Create a company account
            </ButtonLink>
            <ButtonLink href="/reviewers/apply">Apply as a reviewer</ButtonLink>
          </div>
        </div>
        <ExampleSegment />
      </section>

      <section className="border-y border-border bg-surface">
        <div className="mx-auto grid max-w-6xl gap-px px-4 md:grid-cols-3 md:px-6">
          {[
            {
              icon: Icons.upload,
              title: "Upload a file",
              body: "DOCX, XLSX, PPTX, HTML, Markdown, JSON, PO and XLIFF. Your TM and glossary are applied before any engine runs.",
            },
            {
              icon: Icons.scale,
              title: "See the price per tier",
              body: "Each tier shows its price, the expected share of segments approved without a human, and the delivery estimate.",
            },
            {
              icon: Icons.check,
              title: "Get evidence per segment",
              body: "Quality score, senate votes, reviewer edits and annotated errors for every segment, exportable as JSON or PDF.",
            },
          ].map((s) => (
            <div key={s.title} className="py-8 md:px-6 md:first:pl-0 md:last:pr-0">
              <s.icon className="size-5 text-accent" />
              <h2 className="mt-3 text-[15px] font-semibold">{s.title}</h2>
              <p className="mt-1.5 text-[14px] leading-relaxed text-muted">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 md:px-6">
        <h2 className="text-xl font-semibold tracking-tight">Four tiers, one rule</h2>
        <p className="mt-1.5 max-w-2xl text-[14.5px] text-muted">
          A tier decides who gets the final word on segments the quality model is unsure about. Whatever you pick, we never
          quietly swap a paid human review for an AI one: if no qualified reviewer is free, your policy decides whether to wait,
          fall back with your consent, or deliver the reviewed part.
        </p>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(["auto", "ai_review", "hybrid", "full"] as const).map((t) => (
            <div key={t} className="rounded-lg border border-border bg-surface p-4 shadow-card">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">{TIER_LABEL[t]}</h3>
                {(t === "hybrid" || t === "full") && <Badge tone="violet">Human review</Badge>}
              </div>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">{TIER_BLURB[t]}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-[13px] text-muted">
          Regulated content (medical, legal, financial) is only offered tiers with human review.
        </p>
      </section>

      <section className="border-t border-border bg-surface">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-14 md:grid-cols-2 md:px-6">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Built for the teams who answer for the result</h2>
            <ul className="mt-4 space-y-3 text-[14.5px] text-muted">
              {[
                "Thresholds are calibrated per content type and language, and auto-approval suspends itself when control samples catch escaped errors.",
                "Glossaries with mandatory, preferred, forbidden and do-not-translate terms, versioned and frozen per job.",
                "Inline formatting tags are protected end to end; an edit that breaks a tag cannot be saved.",
                "API keys, signed webhooks and XLIFF 2.1 export for your own pipeline.",
              ].map((x) => (
                <li key={x} className="flex gap-2.5">
                  <Icons.check className="mt-0.5 size-4 shrink-0 text-ok" />
                  <span>{x}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-border bg-bg p-5">
            <h2 className="text-[15px] font-semibold">Translators and reviewers</h2>
            <p className="mt-1.5 text-[14px] leading-relaxed text-muted">
              Review segments the machines are unsure about, in your language pairs and domains. Pass a short test per pair,
              work from a keyboard-first cockpit, and see the pay for each task before you take it.
            </p>
            <ButtonLink href="/reviewers/apply" className="mt-4" size="sm">
              Apply as a reviewer <Icons.arrowRight className="size-3.5" />
            </ButtonLink>
          </div>
        </div>
      </section>
    </>
  );
}

function ExampleSegment() {
  return (
    <div className="self-center rounded-xl border border-border bg-surface shadow-pop" aria-label="Example of the evidence recorded for one segment">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-[12.5px] font-medium text-muted">Example segment · en → de</span>
        <Badge tone="neutral">Illustration</Badge>
      </div>
      <div className="space-y-3 px-4 py-4">
        <div>
          <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">Source</div>
          <TaggedText value="Press ⟦1⟧Start⟦/1⟧ to begin the infusion." className="text-[14.5px]" />
        </div>
        <div>
          <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-faint">Target</div>
          <TaggedText value="Drücken Sie ⟦1⟧Start⟦/1⟧, um die Infusion zu beginnen." className="text-[14.5px]" />
        </div>
      </div>
      <ol className="space-y-2.5 border-t border-border px-4 py-4 text-[13px]">
        {[
          { label: "Quality estimate", detail: "Score falls inside the uncertainty band", tone: "warn" as const, badge: "Uncertain" },
          { label: "Glossary and tag checks", detail: "Mandatory term present, tags intact", tone: "ok" as const, badge: "Pass" },
          { label: "Senate vote", detail: "Three agents review independently; one dissent on style", tone: "accent" as const, badge: "Approve" },
          { label: "Decision", detail: "Shipped with the full trail in the evidence pack", tone: "ok" as const, badge: "Delivered" },
        ].map((s, i) => (
          <li key={s.label} className="flex items-start gap-3">
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-subtle text-[11px] font-semibold text-muted">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-fg">{s.label}</div>
              <div className="text-muted">{s.detail}</div>
            </div>
            <Badge tone={s.tone}>{s.badge}</Badge>
          </li>
        ))}
      </ol>
    </div>
  );
}
