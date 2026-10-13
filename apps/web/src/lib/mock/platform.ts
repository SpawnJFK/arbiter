// Mock of the platform endpoints (modules, roles, team, audit, SSO) for NEXT_PUBLIC_API_MOCK=1.
import type { AuditEvent, CustomRole, Member, ModuleInfo, SsoConfig } from "../platform-api";
import type { Role } from "../types";

const MODULES: Omit<ModuleInfo, "enabled">[] = [
  { key: "tms", name: "Web translation", depends_on: [] },
  { key: "engine", name: "Translation engine API", depends_on: [] },
  { key: "ai", name: "AI quality layer", depends_on: [] },
  { key: "pm", name: "Project management", depends_on: [] },
  { key: "auditor", name: "Quality auditor", depends_on: [] },
  { key: "strings", name: "Software strings", depends_on: ["tms"] },
  { key: "community", name: "Reviewer marketplace", depends_on: ["tms"] },
];

export const ROLE_PERMS: Record<string, string[]> = {
  admin: ["*"],
  pm: ["*.read", "*.write", "audit.read", "billing.manage", "engines.manage", "org.manage", "vendors.manage"],
  client: ["*.read", "files.write", "jobs.write", "quotes.write"],
  reviewer: ["tasks.read", "tasks.write"],
};

const CATALOG = [
  "projects.read", "projects.write", "jobs.read", "jobs.write", "assets.read", "assets.write", "quality.read",
  "crm.read", "crm.write", "billing.read", "billing.manage", "org.manage", "users.read", "users.write",
  "roles.write", "audit.read",
].map((key) => ({ key, description: key }));

interface PlatformStore {
  modules: string[];
  roles: CustomRole[];
  members: Member[];
  audit: AuditEvent[];
  sso: SsoConfig;
}

const now = () => new Date().toISOString();
const id = (p: string) => `${p}_${Math.random().toString(36).slice(2, 12).toUpperCase()}`;

function createStore(): PlatformStore {
  const t0 = Date.now();
  const ago = (h: number) => new Date(t0 - h * 3600_000).toISOString();
  const roles: CustomRole[] = [
    {
      id: "rol_01JAUDITOR",
      name: "Auditor",
      description: "Reads projects and the audit log, changes nothing.",
      base_role: "client",
      permissions: ["audit.read", "jobs.read", "projects.read"],
      members: 1,
      created_at: ago(400),
    },
  ];
  return {
    modules: MODULES.map((m) => m.key),
    roles,
    members: [
      { id: "usr_01JPM", email: "pm@demo.test", name: "Mira Petrovic", role: "pm", role_id: null, role_name: null, status: "active", created_at: ago(900) },
      { id: "usr_01JCLIENT", email: "client@demo.test", name: "Jonas Berg", role: "client", role_id: null, role_name: null, status: "active", created_at: ago(700) },
      { id: "usr_01JAUD", email: "audit@demo.test", name: "Ana Ilic", role: "client", role_id: "rol_01JAUDITOR", role_name: "Auditor", status: "active", created_at: ago(300) },
      { id: "usr_01JINV", email: "new.hire@demo.test", name: "", role: "client", role_id: null, role_name: null, status: "invited", created_at: ago(5) },
    ],
    audit: [
      ["auth.login", "user", "usr_01JPM", {}],
      ["org.updated", "organization", "org_demo", { changes: { default_tier: { from: "hybrid", to: "full" } } }],
      ["api_key.created", "api_key", "key_01JCI", { name: "CI", prefix: "a1b2c3" }],
      ["user.invited", "user", "usr_01JINV", { email: "new.hire@demo.test", role: "client" }],
      ["project.created", "project", "prj_01JSUPQ4", { name: "Spring release", tier: "hybrid" }],
    ].map(([action, ttype, tid, data], i) => ({
      id: `aud_${i}`,
      at: ago(i * 7 + 1),
      actor: { type: "user", id: "usr_01JPM", label: "pm@demo.test" },
      action: action as string,
      target: { type: ttype as string, id: tid as string },
      ip: "203.0.113.24",
      user_agent: "Mozilla/5.0 (demo)",
      data: data as Record<string, unknown>,
    })),
    sso: {
      configured: false,
      enabled: false,
      issuer: "",
      client_id: "",
      client_secret_set: false,
      default_role: "client",
      default_role_id: null,
      enforce_sso: false,
      redirect_uri: "http://localhost:3000/api/sso/callback",
      domains: [],
    },
  };
}

const g = globalThis as unknown as { __arbiterPlatformMock?: PlatformStore };
export function platformStore(): PlatformStore {
  g.__arbiterPlatformMock ??= createStore();
  return g.__arbiterPlatformMock;
}

function effective(enabled: string[]): string[] {
  return MODULES.filter((m) => enabled.includes(m.key) && m.depends_on.every((d) => enabled.includes(d))).map((m) => m.key);
}

export function mockModules(): string[] {
  return effective(platformStore().modules);
}

function catalog(): ModuleInfo[] {
  const on = mockModules();
  return MODULES.map((m) => ({ ...m, enabled: on.includes(m.key) }));
}

const json = (data: unknown, status = 200) => Response.json(data, { status });
const err = (status: number, code: string, message: string) => json({ error: { code, message, details: {} } }, status);

/** Returns null when the path is not a platform endpoint. */
export function platformRoute(method: string, parts: string[], body: Record<string, unknown>, role: Role, org: { id: string; name: string; slug: string; plan: string }): Response | null {
  const s = platformStore();
  const [a, b, c, d] = parts;
  const customer = role === "pm" || role === "client";
  const perms = ROLE_PERMS[role] ?? [];
  const has = (p: string) => perms.some((x) => x === "*" || x === p || (x.endsWith(".*") && p.startsWith(x.slice(0, -1))) || (x.startsWith("*.") && p.endsWith(x.slice(1)) && p !== "audit.read"));

  if (a === "org" && b === "modules" && method === "GET") return customer ? json({ enabled: mockModules(), catalog: catalog() }) : err(403, "forbidden", "Customers only.");
  if (a === "admin" && b === "orgs" && c && role === "admin") {
    if (!d && method === "GET") return json({ ...org, id: c, kind: "client", modules: mockModules(), catalog: catalog() });
    if (d === "modules" && method === "PUT") {
      s.modules = ((body.modules as string[]) ?? []).filter((k) => MODULES.some((m) => m.key === k));
      return json({ enabled: mockModules(), catalog: catalog() });
    }
  }
  if (a === "roles") {
    if (!has("users.read")) return err(403, "forbidden", "Missing permission users.read.");
    if (!b && method === "GET") return json({ items: s.roles, next_offset: null, builtin: [{ key: "pm" }, { key: "client" }], catalog: CATALOG });
    if (!has("roles.write")) return err(403, "forbidden", "Missing permission roles.write.");
    if (!b && method === "POST") {
      const r: CustomRole = { id: id("rol"), name: String(body.name), description: String(body.description ?? ""), base_role: (body.base_role as "pm" | "client") ?? "client", permissions: (body.permissions as string[]) ?? [], members: 0, created_at: now() };
      s.roles.push(r);
      return json(r, 201);
    }
    const r = s.roles.find((x) => x.id === b);
    if (!r) return err(404, "not_found", "Role not found.");
    if (method === "PATCH") {
      Object.assign(r, body);
      return json(r);
    }
    if (method === "DELETE") {
      if (r.members) return err(409, "conflict", "The role is assigned to team members.");
      s.roles = s.roles.filter((x) => x.id !== b);
      return new Response(null, { status: 204 });
    }
  }
  if (a === "users") {
    if (!b && method === "GET") return has("users.read") ? json({ items: s.members, next_offset: null }) : err(403, "forbidden", "Missing permission users.read.");
    if (!has("users.write")) return err(403, "forbidden", "Missing permission users.write.");
    if (b === "invite" && method === "POST") {
      const roleId = (body.role_id as string) || null;
      const m: Member = { id: id("usr"), email: String(body.email).toLowerCase(), name: String(body.name ?? ""), role: roleId ? (s.roles.find((r) => r.id === roleId)?.base_role ?? "client") : ((body.role as "pm" | "client") ?? "client"), role_id: roleId, role_name: s.roles.find((r) => r.id === roleId)?.name ?? null, status: "invited", created_at: now() };
      s.members.push(m);
      return json({ user: m, expires_at: now(), email_sent: false, invite_token: "demo-token", invite_url: "http://localhost:3000/accept-invite?token=demo-token" }, 201);
    }
    const m = s.members.find((x) => x.id === b);
    if (!m) return err(404, "not_found", "User not found.");
    if (method === "PATCH") {
      if ("role_id" in body) {
        const r = s.roles.find((x) => x.id === body.role_id);
        m.role_id = r?.id ?? null;
        m.role_name = r?.name ?? null;
        m.role = r?.base_role ?? (body.role as "pm" | "client") ?? m.role;
      } else if (body.role) m.role = body.role as "pm" | "client";
      if (body.is_active === true) m.status = "active";
      return json(m);
    }
    if (method === "DELETE") {
      m.status = "deactivated";
      return new Response(null, { status: 204 });
    }
  }
  if (a === "audit" && method === "GET") {
    if (!has("audit.read")) return err(403, "forbidden", "Missing permission audit.read.");
    if (b === "export") return new Response("at,action\n", { headers: { "Content-Type": "text/csv" } });
    return json({ items: s.audit, next_offset: null });
  }
  if (a === "org" && b === "sso") {
    if (!has("org.manage")) return err(403, "forbidden", "Missing permission org.manage.");
    if (!c && method === "GET") return json(s.sso);
    if (!c && method === "PUT") {
      const domains = ((body.allowed_domains as string[]) ?? []).map((dm) => s.sso.domains.find((x) => x.domain === dm) ?? { domain: dm, verified: false, verified_at: null, txt_record: `arbiter-verify=${Math.random().toString(16).slice(2, 18)}` });
      s.sso = { ...s.sso, configured: true, enabled: Boolean(body.enabled), issuer: String(body.issuer), client_id: String(body.client_id), client_secret_set: s.sso.client_secret_set || Boolean(body.client_secret), default_role: (body.default_role as "pm" | "client") ?? "client", default_role_id: (body.default_role_id as string) ?? null, enforce_sso: Boolean(body.enforce_sso), domains };
      return json(s.sso);
    }
    if (!c && method === "DELETE") {
      s.sso = createStore().sso;
      return new Response(null, { status: 204 });
    }
    if (c === "domains" && parts[4] === "verify" && method === "POST") {
      const dm = s.sso.domains.find((x) => x.domain === d);
      if (!dm) return err(404, "not_found", "Domain not found.");
      dm.verified = true;
      dm.verified_at = now();
      return json(s.sso);
    }
  }
  return null;
}
