import { ApiError, parseError } from "./api";
import type { User } from "./types";

/** Calls the /api/session route handler, which sets the httpOnly cookie. */
export async function startSession(
  kind: "login" | "register" | "apply" | "reset",
  body: Record<string, unknown>,
  next?: string | null,
): Promise<{ user: User; redirect: string }> {
  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, next, ...body }),
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as { user: User; redirect: string };
}

export function fieldErrors(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError)) return {};
  const d = e.details as { fields?: Record<string, string> } & Record<string, unknown>;
  if (d?.fields && typeof d.fields === "object") return d.fields;
  return {};
}

/** POST /api/password/forgot: always resolves the same way, whether or not the address exists. */
export async function requestPasswordReset(email: string): Promise<void> {
  const res = await fetch("/api/password/forgot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw await parseError(res);
}
