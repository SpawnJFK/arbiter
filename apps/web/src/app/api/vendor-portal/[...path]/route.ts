import { NextResponse, type NextRequest } from "next/server";
import { backendFetch, UNREACHABLE_HEADER } from "@/lib/backend";
import { getI18n } from "@/lib/i18n/server";

type Ctx = { params: Promise<{ path: string[] }> };

const FORWARD_REQ = ["accept", "content-type"];
const FORWARD_RES = ["content-type", "content-disposition", "content-length"];

/**
 * Public proxy for the vendor workbench (module pm): /api/vendor-portal/<token>/<...> ->
 * <API>/v1/vendor-portal/<token>/<...>. No session: the signed token in the path is the only
 * credential, and nothing outside /vendor-portal can be reached through here.
 */
async function handle(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  if (path.length === 0 || path.some((p) => p === ".." || p === "." || p === "")) {
    return NextResponse.json({ error: { code: "bad_path", message: "Invalid path.", details: {} } }, { status: 400 });
  }
  const headers = new Headers();
  for (const h of FORWARD_REQ) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const body = hasBody ? await req.arrayBuffer() : null;
  const upstream = await backendFetch(`/vendor-portal/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`, {
    method: req.method,
    headers,
    body: body && body.byteLength > 0 ? body : null,
    token: null,
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
