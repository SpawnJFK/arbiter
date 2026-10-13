// Platform endpoints (docs/api-contract.md, "Platform: modules, roles, team, audit log, SSO").
// Spread into createApi() so both transports (browser proxy, server) expose them.
import type { Query, Transport } from "./api";
import type { ListParams, ListResponse } from "./types";

export interface ModuleInfo {
  key: string;
  name: string;
  depends_on: string[];
  enabled: boolean;
}

/** Paid add-on on top of a module (D-077). Billing writes them; the org UI only shows them. */
export interface AddonInfo {
  key: string;
  name: string;
  module: string;
  enabled: boolean;
}

export interface OrgModules {
  enabled: string[];
  catalog: ModuleInfo[];
  addons?: AddonInfo[];
}

export interface CustomRole {
  id: string;
  name: string;
  description: string;
  base_role: "pm" | "client";
  permissions: string[];
  members: number;
  created_at: string | null;
}

export interface RolesResponse extends ListResponse<CustomRole> {
  builtin: { key: string }[];
  catalog: { key: string; description: string }[];
}

export type RoleInput = Pick<CustomRole, "name" | "description" | "base_role" | "permissions">;

export type MemberStatus = "active" | "invited" | "deactivated";

export interface Member {
  id: string;
  email: string;
  name: string;
  role: "pm" | "client";
  role_id: string | null;
  role_name: string | null;
  status: MemberStatus;
  created_at: string | null;
}

export interface InviteResult {
  user: Member;
  expires_at: string;
  email_sent: boolean;
  invite_token?: string;
  invite_url?: string;
}

export interface AuditEvent {
  id: string;
  at: string;
  actor: { type: "user" | "api_key" | "system"; id: string; label: string };
  action: string;
  target: { type: string; id: string };
  ip: string;
  user_agent: string;
  data: Record<string, unknown>;
}

export interface AuditFilters {
  actor?: string;
  action?: string;
  since?: string;
  until?: string;
}

export interface SsoDomain {
  domain: string;
  verified: boolean;
  verified_at: string | null;
  txt_record: string;
}

export interface SsoConfig {
  configured: boolean;
  enabled: boolean;
  issuer: string;
  client_id: string;
  client_secret_set: boolean;
  default_role: "pm" | "client";
  default_role_id: string | null;
  enforce_sso: boolean;
  redirect_uri: string;
  domains: SsoDomain[];
}

export interface SsoInput {
  issuer: string;
  client_id: string;
  client_secret?: string | null;
  allowed_domains: string[];
  default_role: "pm" | "client";
  default_role_id?: string | null;
  enforce_sso: boolean;
  enabled: boolean;
}

export interface AdminOrg {
  id: string;
  name: string;
  slug: string;
  plan: string;
  kind?: string;
  modules?: string[];
  catalog: ModuleInfo[];
  addons?: AddonInfo[];
}

const enc = encodeURIComponent;

export function platformEndpoints(item: Transport) {
  const get = <T>(path: string, query?: Query) => item.request<T>("GET", path, { query });
  const send = <T>(method: string, path: string, body?: unknown) => item.request<T>(method, path, { body });
  const page = (p?: ListParams): Query => ({ offset: p?.offset, limit: p?.limit });

  return {
    orgModules: () => get<OrgModules>("/org/modules"),
    adminOrg: (id: string) => get<AdminOrg>(`/admin/orgs/${enc(id)}`),
    setOrgModules: (id: string, modules: string[]) => send<OrgModules>("PUT", `/admin/orgs/${enc(id)}/modules`, { modules }),

    roles: () => get<RolesResponse>("/roles"),
    createRole: (body: RoleInput) => send<CustomRole>("POST", "/roles", body),
    updateRole: (id: string, body: Partial<RoleInput>) => send<CustomRole>("PATCH", `/roles/${enc(id)}`, body),
    deleteRole: (id: string) => send<null>("DELETE", `/roles/${enc(id)}`),

    members: (p?: ListParams) => get<ListResponse<Member>>("/users", page(p)),
    inviteMember: (body: { email: string; name?: string; role?: "pm" | "client"; role_id?: string }) =>
      send<InviteResult>("POST", "/users/invite", body),
    updateMember: (id: string, body: { name?: string; role?: "pm" | "client"; role_id?: string | null; is_active?: boolean }) =>
      send<Member>("PATCH", `/users/${enc(id)}`, body),
    deactivateMember: (id: string) => send<null>("DELETE", `/users/${enc(id)}`),

    auditLog: (f: AuditFilters & ListParams = {}) => get<ListResponse<AuditEvent>>("/audit", { ...f, ...page(f) }),
    auditLogExportUrl: (f: AuditFilters = {}) => item.downloadUrl("/audit/export", { ...f }),

    sso: () => get<SsoConfig>("/org/sso"),
    saveSso: (body: SsoInput) => send<SsoConfig>("PUT", "/org/sso", body),
    deleteSso: () => send<null>("DELETE", "/org/sso"),
    verifySsoDomain: (domain: string) => send<SsoConfig>("POST", `/org/sso/domains/${enc(domain)}/verify`),
  };
}
