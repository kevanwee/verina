import { ACCOUNT } from "@/lib/connected/copy-accounts";
import { SignOutButton } from "./ConnectedFrame";
import form from "../../workbench/intake/intake.module.css";
import styles from "../connected.module.css";

/**
 * Shown in place of a connected page when the API refused the signed-in token (401) or
 * Verina could not be reached. No data is shown in either case.
 */
export function ViewerProblem({
  kind,
  retryHref,
}: {
  kind: "rejected" | "unavailable";
  retryHref: string;
}) {
  const rejected = kind === "rejected";
  return (
    <section className={styles.narrow} aria-labelledby="viewer-problem">
      <div className={styles.pageHead}>
        <h1 id="viewer-problem" className={styles.pageTitle}>
          {rejected ? ACCOUNT.REJECTED_HEADING : ACCOUNT.UNAVAILABLE_HEADING}
        </h1>
        <p className={styles.lede}>{rejected ? ACCOUNT.REJECTED_BODY : ACCOUNT.UNAVAILABLE_BODY}</p>
      </div>
      <div className={styles.inlineActions}>
        {rejected ? (
          <SignOutButton className={form.buttonQuiet} />
        ) : (
          <a className={form.buttonPrimary} href={retryHref}>
            {ACCOUNT.TRY_AGAIN}
          </a>
        )}
      </div>
    </section>
  );
}
