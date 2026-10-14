"use client";

import { useEffect, useRef } from "react";
import { signInHref } from "@/lib/connected/auth/client";
import { C, TITLES } from "@/lib/connected/copy";
import { SignOutButton } from "../_components/ConnectedFrame";
import styles from "../../workbench/intake/intake.module.css";

/**
 * Signed out (C-01, C-02) or account not set up (C-09). No matter request is sent from
 * either state. The heading takes focus on entry; the action is next in order.
 */
export function SessionPanel({ kind, returnTo }: { kind: "signed_out" | "not_set_up"; returnTo: string }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
    if (kind === "signed_out") document.title = TITLES.signIn;
  }, [kind]);

  if (kind === "not_set_up") {
    return (
      <section className={styles.requester} aria-labelledby="session-heading">
        <h2 id="session-heading" ref={headingRef} tabIndex={-1} className={styles.panelHeading}>
          {C.C09_HEADING}
        </h2>
        <p>{C.C09_BODY}</p>
        <div className={styles.formActions}>
          <SignOutButton className={styles.buttonQuiet} />
        </div>
      </section>
    );
  }

  return (
    <section className={styles.requester} aria-labelledby="session-heading">
      <h2 id="session-heading" ref={headingRef} tabIndex={-1} className={styles.panelHeading}>
        {C.C01_HEADING}
      </h2>
      <p>{C.C02_BODY}</p>
      <div className={styles.formActions}>
        <a className={styles.buttonPrimary} href={signInHref(returnTo)}>
          {C.C02_BUTTON}
        </a>
      </div>
    </section>
  );
}
