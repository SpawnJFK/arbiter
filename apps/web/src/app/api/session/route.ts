import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { IS_MOCK, ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/config";
import { mockApply, mockLogin, mockRegister } from "@/lib/mock/handler";
import { safeNext } from "@/lib/roles";
import type { User } from "@/lib/types";

type Kind = "login" | "register" | "apply";
const PATHS: Record<Kind, string> = {
  login: "/auth/login",
  register: "/auth/register",
  apply: "/reviewers/apply",
};
const MAX_AGE = 60 * 60 * 12; // 12 h; the backend's JWT expiry still wins (401 -> /logout)

function errorJson(status: number, code: string, message: string) {
  return NextResponse.json({ error: { code, message, details: {} } }, { status });
}

/**
 * POST /api/session  { kind: "login"|"register"|"apply", next?, ...contract body }
 * Proxies to the backend auth endpoint, stores the token in an httpOnly cookie and returns
 * only `{ user, redirect }` so the token never reaches browser JavaScript.
 */
export async function POST(req: NextRequest) {
  let payload: Record<string, unknown>;
  try {
    payload = (await req.json()) as Record<string, unknown>;
  } catch {
    return errorJson(400, "invalid_json", "Body must be JSON.");
  }
  const kind = payload.kind as Kind;
  if (!PATHS[kind]) return errorJson(400, "invalid_kind", "kind must be login, register or apply.");
  const { kind: _k, next, ...body } = payload;
  void _k;

  let token: string;
  let user: User;
  if (IS_MOCK) {
    const email = String(body.email ?? "");
    if (!email || !body.password) return errorJson(422, "validation_error", "Email and password are required.");
    const r =
      kind === "login"
        ? mockLogin(email)
        : kind === "register"
          ? mockRegister(body as { org_name: string; name: string; email: string })
          : mockApply(body as Parameters<typeof mockApply>[0]);
    token = r.token;
    user = r.user;
  } else {
    const res = await backendFetch(PATHS[kind], {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as { token?: string; user?: User } | null;
    if (!res.ok || !data?.token || !data.user) {
      return NextResponse.json(data ?? { error: { code: "auth_failed", message: "Sign-in failed.", details: {} } }, {
        status: res.ok ? 502 : res.status,
      });
    }
    token = data.token;
    user = data.user;
  }

  const jar = await cookies();
  const opts = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production" && req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: MAX_AGE,
  };
  jar.set(TOKEN_COOKIE, token, opts);
  jar.set(ROLE_COOKIE, user.role, opts);
  return NextResponse.json({ user, redirect: safeNext(typeof next === "string" ? next : null, user.role) });
}

/** DELETE /api/session: sign out. */
export async function DELETE() {
  const jar = await cookies();
  jar.delete(TOKEN_COOKIE);
  jar.delete(ROLE_COOKIE);
  return new NextResponse(null, { status: 204 });
}
