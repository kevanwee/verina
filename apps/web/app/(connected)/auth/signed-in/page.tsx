import type { Metadata } from "next";
import { Suspense } from "react";
import { AUTH } from "@/lib/connected/copy-accounts";
import { requireConnected } from "@/lib/connected/server-gate";
import { AuthBroadcast } from "../../_components/AuthBroadcast";
import { ConnectedFrame, PageSkeleton } from "../../_components/ConnectedFrame";
import styles from "../../connected.module.css";

export const metadata: Metadata = {
  title: "Signed in | Verina",
  robots: { index: false, follow: false },
};

/** Landing page of the separate sign-in window opened by reauthenticate(). */
async function SignedIn() {
  await requireConnected();
  return (
    <div className={styles.narrow}>
      <AuthBroadcast message="signed-in" />
      <div className={styles.pageHead}>
        <h1 className={styles.pageTitle}>{AUTH.SIGNED_IN_HEADING}</h1>
        <p className={styles.lede}>{AUTH.SIGNED_IN_BODY}</p>
      </div>
    </div>
  );
}

export default function SignedInPage() {
  return (
    <ConnectedFrame>
      <Suspense fallback={<PageSkeleton label={AUTH.SIGNED_IN_HEADING} />}>
        <SignedIn />
      </Suspense>
    </ConnectedFrame>
  );
}
