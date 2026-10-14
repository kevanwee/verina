import { ACCOUNT } from "@/lib/connected/copy-accounts";
import { SignOutButton } from "./ConnectedFrame";
import form from "../../workbench/intake/intake.module.css";
import styles from "../connected.module.css";

/**
 * Neutral page for a valid sign-in with no organization link (GET /v1/me returned
 * linked:false). Shows no data at all, only the explanation and sign-out.
 */
export function NotLinked() {
  return (
    <section className={styles.narrow} aria-labelledby="not-linked-title">
      <div className={styles.pageHead}>
        <h1 id="not-linked-title" className={styles.pageTitle}>
          {ACCOUNT.NOT_LINKED_HEADING}
        </h1>
        <p className={styles.lede}>{ACCOUNT.NOT_LINKED_BODY}</p>
        <p className={styles.note}>{ACCOUNT.NOT_LINKED_NOTE}</p>
      </div>
      <div className={styles.inlineActions}>
        <SignOutButton className={form.buttonQuiet} />
      </div>
    </section>
  );
}
