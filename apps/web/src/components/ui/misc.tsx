import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Kbd({ children, className, inverse }: { children: ReactNode; className?: string; inverse?: boolean }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border px-1 font-mono text-[11px] font-medium",
        inverse ? "border-current/40 text-current" : "border-border-strong border-b-2 bg-surface text-muted",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <div className="mb-3 flex size-10 items-center justify-center rounded-full bg-subtle text-faint">
        {icon ?? (
          <svg viewBox="0 0 20 20" fill="none" className="size-5" aria-hidden="true">
            <rect x="3" y="4" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <path d="M3 8h14" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        )}
      </div>
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description && <p className="mt-1 max-w-md text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Progress({ value, className, tone = "accent" }: { value: number; className?: string; tone?: "accent" | "ok" | "danger" }) {
  const pctVal = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div
      role="progressbar"
      aria-valuenow={pctVal}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-subtle", className)}
    >
      <div
        className={cn("h-full rounded-full", tone === "ok" ? "bg-ok" : tone === "danger" ? "bg-danger" : "bg-accent")}
        style={{ width: `${pctVal}%` }}
      />
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[12.5px] text-muted">{eyebrow}</div>}
        <h1 className="text-lg font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-0.5 max-w-2xl text-[13.5px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "warn" | "danger" | "ok";
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const t = {
    info: "border-info/25 bg-info-subtle",
    warn: "border-warn/30 bg-warn-subtle",
    danger: "border-danger/30 bg-danger-subtle",
    ok: "border-ok/30 bg-ok-subtle",
  }[tone];
  const fg = { info: "text-info", warn: "text-warn", danger: "text-danger", ok: "text-ok" }[tone];
  return (
    <div className={cn("rounded-lg border px-3.5 py-2.5 text-[13.5px]", t, className)} role={tone === "danger" ? "alert" : undefined}>
      {title && <div className={cn("mb-0.5 font-semibold", fg)}>{title}</div>}
      <div className="text-fg/90">{children}</div>
    </div>
  );
}

/** Small mono id with optional copy affordance handled elsewhere. */
export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[12.5px] text-muted", className)}>{children}</span>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-subtle", className)} aria-hidden="true" />;
}
