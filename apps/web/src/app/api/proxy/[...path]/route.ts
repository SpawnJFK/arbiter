import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch, UNREACHABLE_HEADER } from "@/lib/backend";
import { getI18n } from "@/lib/i18n/server";
import { TOKEN_COOKIE } from "@/lib/config";

type Ctx = { params: Promise<{ path: string[] }> };

// Request headers worth forwarding to the backend; everything else (cookies!) stays here.
const FORWARD_REQ = ["accept", "content-type", "idempotency-key", "if-none-match"];
// Response headers worth passing back to the browser.
const FORWARD_RES = ["content-type", "content-disposition", "content-length", "etag", "cache-control", "retry-after"];

/**
 * Thin authenticated proxy: /api/proxy/<path> -> <API>/v1/<path>, adding the Bearer token from
 * the httpOnly cookie. Bodies (JSON or multipart) are forwarded byte-for-byte.
 */
async function handle(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  if (path.some((p) => p === ".." || p === ".")) {
    return NextResponse.json({ error: { code: "bad_path", message: "Invalid path.", details: {} } }, { status: 400 });
  }
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) {
    const { t } = await getI18n();
    return NextResponse.json({ error: { code: "unauthenticated", message: t("errors.signInFirst"), details: {} } }, { status: 401 });
  }

  const headers = new Headers();
  for (const h of FORWARD_REQ) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const body = hasBody ? await req.arrayBuffer() : null;

  const upstream = await backendFetch(`/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`, {
    method: req.method,
    headers,
    body: body && body.byteLength > 0 ? body : null,
    token,
  });

  if (upstream.headers.get(UNREACHABLE_HEADER)) {
    const { t } = await getI18n();
    return NextResponse.json({ error: { code: "backend_unreachable", message: t("errors.backendUnreachable"), details: {} } }, { status: 502 });
  }

  const outHeaders = new Headers({ "Cache-Control": "no-store" });
  for (const h of FORWARD_RES) {
    const v = upstream.headers.get(h);
    if (v) outHeaders.set(h, v);
  }
  return new NextResponse(upstream.status === 204 ? null : upstream.body, { status: upstream.status, headers: outHeaders });
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
