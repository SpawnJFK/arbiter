// Runtime configuration shared by server and client code.

/** Mock mode: answer every API call from fixtures in src/lib/mock (inlined at build time). */
export const IS_MOCK = process.env.NEXT_PUBLIC_API_MOCK === "1";

/**
 * Backend origin (without the /v1 suffix). Only the Next server talks to it; the browser
 * goes through /api/proxy. `API_URL` lets a container override the build-time public value.
 */
export function apiOrigin(): string {
  const raw = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return raw.replace(/\/+$/, "").replace(/\/v1$/, "");
}

export const TOKEN_COOKIE = "arbiter_token";
export const ROLE_COOKIE = "arbiter_role";
