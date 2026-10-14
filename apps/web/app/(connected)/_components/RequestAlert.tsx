import type { ReactNode, Ref } from "react";
import { Warning, WarningOctagon } from "@phosphor-icons/react/dist/ssr";
import styles from "../connected.module.css";

/**
 * A blocking problem, rendered inside the panel that owns the action (role="alert", read
 * once). The heading takes focus (tabIndex -1) so keyboard and screen-reader users land on
 * it. "unknown" is for outcomes that may or may not have been recorded.
 */
export function RequestAlert({
  id,
  tone = "error",
  heading,
  children,
  actions,
  headingRef,
}: {
  id?: string;
  tone?: "error" | "unknown";
  heading: string;
  children: ReactNode;
  actions?: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  const Icon = tone === "unknown" ? Warning : WarningOctagon;
  return (
    <div id={id} role="alert" className={styles.alert} data-tone={tone}>
      <h3 ref={headingRef} tabIndex={-1} className={styles.alertHeading}>
        <Icon weight="bold" aria-hidden="true" focusable="false" />
        {heading}
      </h3>
      {children}
      {actions ? <div className={styles.inlineActions}>{actions}</div> : null}
    </div>
  );
}
