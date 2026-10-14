import { ACCOUNT, ROLE_LABELS } from "@/lib/connected/copy-accounts";
import type { LinkedMe } from "@/lib/connected/me";
import styles from "../connected.module.css";

/** US-52: the signed-in person's name, organization and roles, as GET /v1/me returns them. */
export function AccountDetails({ me }: { me: LinkedMe }) {
  return (
    <section className={styles.page} aria-labelledby="account-title">
      <div className={styles.pageHead}>
        <h1 id="account-title" className={styles.pageTitle}>
          {ACCOUNT.TITLE}
        </h1>
        <p className={styles.lede}>{ACCOUNT.LEDE}</p>
      </div>
      <dl className={styles.facts}>
        <div>
          <dt>{ACCOUNT.NAME}</dt>
          <dd>{me.displayName}</dd>
        </div>
        <div>
          <dt>{ACCOUNT.ORGANIZATION}</dt>
          <dd>{me.organization ? me.organization.name : ACCOUNT.NO_ORGANIZATION}</dd>
        </div>
        <div>
          <dt>{ACCOUNT.ROLES}</dt>
          <dd>
            {me.roles.length > 0 ? (
              <ul className={styles.roleList}>
                {me.roles.map((role) => (
                  <li key={role} className={styles.roleTag}>
                    {ROLE_LABELS[role]}
                  </li>
                ))}
              </ul>
            ) : (
              ACCOUNT.NO_ROLES
            )}
          </dd>
        </div>
        {me.platformAdmin ? (
          <div>
            <dt>{ACCOUNT.ACCESS}</dt>
            <dd>{ACCOUNT.PLATFORM_ADMIN}</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}
