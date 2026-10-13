import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { can } from "@/lib/modules";
import { getMe, withAuth } from "@/lib/server-api";
import { Team } from "./team";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("platform.team.metaTitle") };
}

export default async function TeamPage() {
  const me = await getMe();
  const [members, roles] = await withAuth(
    (api) => Promise.all([api.members({ limit: 200 }), api.roles()]),
    "/app/settings/team",
  );
  return (
    <Team
      initialMembers={members.items}
      initialRoles={roles.items}
      catalog={roles.catalog}
      meId={me.user.id}
      canManageUsers={can(me, "users.write")}
      canManageRoles={can(me, "roles.write")}
    />
  );
}
