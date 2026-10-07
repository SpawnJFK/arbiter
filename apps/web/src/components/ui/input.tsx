import { useId, type ComponentProps, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

const control =
  "w-full rounded-md border border-border-strong bg-surface px-2.5 text-sm text-fg placeholder:text-faint shadow-card transition-colors hover:border-faint focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-ring disabled:opacity-60 aria-[invalid=true]:border-danger";

export function Input({ className, ...rest }: ComponentProps<"input">) {
  return <input className={cn(control, "h-8.5", className)} {...rest} />;
}

export function Textarea({ className, ...rest }: ComponentProps<"textarea">) {
  return <textarea className={cn(control, "min-h-20 py-2 leading-relaxed", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select className={cn(control, "h-8.5 appearance-none pr-8")} {...rest}>
        {children}
      </select>
      <svg
        className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export function Checkbox({
  label,
  hint,
  className,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <input id={id} type="checkbox" className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]" {...rest} />
      <label htmlFor={id} className="text-sm">
        <span className="text-fg">{label}</span>
        {hint && <span className="mt-0.5 block text-[13px] text-muted">{hint}</span>}
      </label>
    </div>
  );
}

export function Label({ htmlFor, children, className }: { htmlFor?: string; children: ReactNode; className?: string }) {
  return (
    <label htmlFor={htmlFor} className={cn("mb-1 block text-[13px] font-medium text-fg", className)}>
      {children}
    </label>
  );
}

/** Label + control + hint/error. Pass a render function to receive the generated id. */
export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: (id: string, describedBy: string | undefined) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const hintId = hint || error ? `${id}-hint` : undefined;
  return (
    <div className={className}>
      <Label htmlFor={id}>{label}</Label>
      {children(id, hintId)}
      {(hint || error) && (
        <p id={hintId} className={cn("mt-1 text-[12.5px]", error ? "text-danger" : "text-muted")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}
