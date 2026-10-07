import type { Metadata } from "next";
import Link from "next/link";
import { ApplyForm } from "./apply-form";

export const metadata: Metadata = { title: "Apply as a reviewer" };

export default function ApplyPage() {
  return (
    <div className="mx-auto grid max-w-5xl gap-10 px-4 py-12 md:grid-cols-[1fr_1.3fr] md:px-6 md:py-16">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Review translations where it matters</h1>
        <p className="mt-2 text-[14.5px] leading-relaxed text-muted">
          Arbiter sends you the segments the machines are not sure about, in your language pairs and domains. You accept, edit or
          escalate, and annotate errors on a shared MQM scale.
        </p>
        <ol className="mt-6 space-y-4 text-[14px]">
          {[
            ["Apply", "Tell us your language pairs and the domains you know."],
            ["Pass a test per pair", "A short timed test with real segments. Each pair unlocks separately."],
            ["Work from the cockpit", "Keyboard-first review with glossary terms, context and the pay for each task shown up front."],
            ["Get paid", "Earnings accrue per decision. Payouts start once your tax and payout details are on file."],
          ].map(([t, d], i) => (
            <li key={t} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-[12px] font-semibold text-accent">
                {i + 1}
              </span>
              <div>
                <div className="font-medium">{t}</div>
                <div className="text-muted">{d}</div>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-[13.5px] text-muted">
          Already applied? <Link href="/login" className="font-medium text-accent hover:underline">Sign in</Link>
        </p>
      </div>
      <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
        <ApplyForm />
      </div>
    </div>
  );
}
