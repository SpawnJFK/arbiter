import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { ApiError, createApi, parseError, toQueryString, type Api, type Transport } from "./api";
import { backendFetch } from "./backend";
import { ROLE_COOKIE, TOKEN_COOKIE } from "./config";
import type { Me } from "./types";

function serverTransport(token: string | null): Transport {
  return {
    async request<T>(method: string, path: string, opts: Parameters<Transport["request"]>[2] = {}) {
      const headers: Record<string, string> = { Accept: "application/json" };
      let body: BodyInit | undefined;
      if (opts.form) body = opts.form;
      else if (opts.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(opts.body);
      }
      if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
      const res = await backendFetch(`${path}${toQueryString(opts.query)}`, { method, headers, body, token });
      if (!res.ok) throw await parseError(res);
      if (res.status === 204) return null as T;
      const text = await res.text();
      return (text ? JSON.parse(text) : null) as T;
    },
    // Downloads always go through the proxy so the browser carries the cookie, not the token.
    downloadUrl: (path, query) => `/api/proxy${path}${toQueryString(query)}`,
  };
}

export async function getSessionToken(): Promise<string | null> {
  return (await cookies()).get(TOKEN_COOKIE)?.value ?? null;
}

export async function getSessionRole(): Promise<string | null> {
  return (await cookies()).get(ROLE_COOKIE)?.value ?? null;
}

export async function getServerApi(): Promise<Api> {
  return createApi(serverTransport(await getSessionToken()));
}

/**
 * Run a server-side API call; on 401 send the user through /logout (clears the stale cookie)
 * back to /login. Other errors propagate to the nearest error boundary.
 */
export async function withAuth<T>(fn: (api: Api) => Promise<T>, next = "/"): Promise<T> {
  const api = await getServerApi();
  try {
    return await fn(api);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      redirect(`/logout?next=${encodeURIComponent(next)}`);
    }
    throw e;
  }
}

/** Current user + org, memoised per request. */
export const getMe = cache(async (): Promise<Me> => withAuth((api) => api.me()));
