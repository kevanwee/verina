import type { Metadata } from "next";
import { MEMBERS } from "@/lib/connected/copy-accounts";
import { canManageMembers } from "@/lib/connected/me";
import { PATHS } from "@/lib/connected/routes";
import { LinkedPage } from "../../_components/LinkedPage";
import { MembersManager } from "../../_components/MembersManager";
import styles from "../../connected.module.css";

export const metadata: Metadata = {
  title: "Members | Verina",
  robots: { index: false, follow: false },
};

/** US-53, tenant_admin: manage the members of their own organization only. */
export default function MembersPage() {
  return (
    <LinkedPage
      path={PATHS.members}
      loadingLabel={MEMBERS.LOADING}
      allow={canManageMembers}
      render={({ me, subject }) => (
        <div className={styles.page}>
          <div className={styles.pageHead}>
            <h1 className={styles.pageTitle}>{MEMBERS.TITLE}</h1>
            <p className={styles.lede}>{MEMBERS.lede(me.organization?.name ?? "")}</p>
          </div>
          <MembersManager orgId={me.organization?.id ?? ""} subject={subject} selfActorId={me.actorId} />
        </div>
      )}
    />
  );
}
