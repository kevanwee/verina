"use client";

import Link from "next/link";
import { organizationPath, parseOrganization } from "@/lib/connected/admin-data";
import { ADMIN, MEMBERS } from "@/lib/connected/copy-accounts";
import { useReauthenticate, useResource } from "@/lib/connected/hooks";
import { PATHS } from "@/lib/connected/routes";
import { PageSkeleton } from "../../../_components/ConnectedFrame";
import { MembersManager } from "../../../_components/MembersManager";
import { OutcomeAlert } from "../../../_components/OutcomeAlert";
import styles from "../../../connected.module.css";

/** US-53, platform admin: one organization's details and its members. */
export function OrganizationDetail({
  orgId,
  subject,
  selfActorId,
}: {
  orgId: string;
  subject: string | null;
  selfActorId: string;
}) {
  const { state, reload: load } = useResource(organizationPath(orgId), parseOrganization);

  const reauthenticate = useReauthenticate(subject, load);

  return (
    <div className={styles.page}>
      <p>
        <Link href={PATHS.admin}>{ADMIN.BACK}</Link>
      </p>
      {state.status === "loading" ? <PageSkeleton label={ADMIN.LOADING_ONE} /> : null}
      {state.status === "failed" ? (
        <OutcomeAlert read outcome={state.outcome} onRetry={() => void load()} onReauthenticate={reauthenticate} />
      ) : null}
      {state.status === "loaded" ? (
        <>
          <div className={styles.pageHead}>
            <h1 className={styles.pageTitle}>{state.data.name}</h1>
            <p className={styles.lede}>{MEMBERS.lede(state.data.name)}</p>
          </div>
          <section aria-labelledby="organization-details" className={styles.stack}>
            <h2 id="organization-details" className={styles.sectionTitle}>
              {ADMIN.DETAILS}
            </h2>
            <dl className={styles.facts}>
              <div>
                <dt>{ADMIN.COL_SLUG}</dt>
                <dd>{state.data.slug}</dd>
              </div>
              <div>
                <dt>{ADMIN.COL_STATUS}</dt>
                <dd>{state.data.active ? ADMIN.ACTIVE : ADMIN.INACTIVE}</dd>
              </div>
            </dl>
          </section>
          <MembersManager orgId={orgId} subject={subject} selfActorId={selfActorId} />
        </>
      ) : null}
    </div>
  );
}
