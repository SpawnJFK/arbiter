import "server-only";
import { apiOrigin, IS_MOCK } from "./config";
import { mockFetch } from "./mock/handler";

/** Set on the synthetic 502 above so route handlers can replace the message with a localized one. */
export const UNREACHABLE_HEADER = "x-arbiter-unreachable";

/**
 * Single server-side entry point to the Arbiter backend. `path` is relative to /v1
 * (e.g. "/jobs/job_1"). Returns the raw Response so callers can stream binaries.
 */
export async function backendFetch(
  path: string,
  init: { method?: string; headers?: HeadersInit; body?: BodyInit | null; token?: string | null } = {},
): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.token) headers.set("Authorization", `Bearer ${init.token}`);

  if (IS_MOCK) {
    return mockFetch(method, path, headers, init.body ?? null);
  }

  const url = path === "/healthz" ? `${apiOrigin()}/healthz` : `${apiOrigin()}/v1${path}`;
  try {
    return await fetch(url, {
      method,
      headers,
      body: method === "GET" || method === "HEAD" ? undefined : init.body,
      cache: "no-store",
      redirect: "manual",
      // Required by undici when streaming a request body.
      ...(init.body instanceof ReadableStream ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    return Response.json(
      { error: { code: "backend_unreachable", message: "The Arbiter API is not reachable.", details: {} } },
      { status: 502, headers: { [UNREACHABLE_HEADER]: "1" } },
    );
  }
}
