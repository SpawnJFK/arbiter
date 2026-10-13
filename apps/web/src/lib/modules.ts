// Module entitlements and permissions on the web side. Mirrors services/api/arbiter/platform
// (modules.py, permissions.py). The API is the authority: hiding a nav section is convenience,
// the route itself answers 404 module_disabled / 403.
import type { Me, Org } from "./types";

export type ModuleKey = "tms" | "engine" | "ai" | "pm" | "auditor" | "strings" | "community";

/** True when the org has the module. No org (admin, reviewer) or an older API without the field = true. */
export function hasModule(org: Pick<Org, "modules"> | null | undefined, module: ModuleKey): boolean {
  if (!org || !Array.isArray(org.modules)) return true;
  return org.modules.includes(module);
}

const EXPLICIT_ONLY = new Set(["audit.read"]);

function match(granted: string, perm: string): boolean {
  if (granted === "*" || granted === perm) return true;
  const [gArea, gAction] = granted.split(".");
  const [pArea, pAction] = perm.split(".");
  if (gArea === "*" && EXPLICIT_ONLY.has(perm)) return false;
  return (gArea === "*" && gAction === pAction) || (gAction === "*" && gArea === pArea);
}

/** has_permission() of the API, on the patterns /me returns. */
export function can(me: Pick<Me, "permissions"> | null | undefined, perm: string): boolean {
  return (me?.permissions ?? []).some((g) => match(g, perm));
}

/** Drop nav items whose module is disabled, then sections left empty. */
export function filterByModule<I extends { module?: ModuleKey }, S extends { items: I[] }>(
  sections: S[],
  org: Pick<Org, "modules"> | null | undefined,
): S[] {
  return sections
    .map((s) => ({ ...s, items: s.items.filter((i) => !i.module || hasModule(org, i.module)) }))
    .filter((s) => s.items.length > 0);
}
