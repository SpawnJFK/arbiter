import type { Role } from "./types";

export function homeForRole(role: string | undefined | null): string {
  switch (role) {
    case "admin":
      return "/admin";
    case "reviewer":
      return "/reviewer";
    case "pm":
    case "client":
      return "/app";
    default:
      return "/login";
  }
}

/** Which roles may enter each area. */
export const AREA_ROLES: Record<"/app" | "/reviewer" | "/admin", Role[]> = {
  "/app": ["pm", "client"],
  "/reviewer": ["reviewer"],
  "/admin": ["admin"],
};

export function areaFor(pathname: string): keyof typeof AREA_ROLES | null {
  for (const area of Object.keys(AREA_ROLES) as (keyof typeof AREA_ROLES)[]) {
    if (pathname === area || pathname.startsWith(`${area}/`)) return area;
  }
  return null;
}

/** Only allow same-site relative redirects after login. */
export function safeNext(next: string | null | undefined, role: string): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return homeForRole(role);
  const area = areaFor(next);
  if (area && !AREA_ROLES[area].includes(role as Role)) return homeForRole(role);
  return next;
}
