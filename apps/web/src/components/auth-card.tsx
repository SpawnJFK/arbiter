import type { ReactNode } from "react";

export function AuthCard({ title, description, children, footer }: { title: string; description?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-md px-4 py-12 md:py-16">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="mt-1 text-[14px] text-muted">{description}</p>}
      <div className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">{children}</div>
      {footer && <div className="mt-4 text-center text-[13.5px] text-muted">{footer}</div>}
    </div>
  );
}
