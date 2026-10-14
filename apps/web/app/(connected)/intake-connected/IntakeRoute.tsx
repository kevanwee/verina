import { Suspense } from "react";
import { redirect } from "next/navigation";
import { Flask } from "@phosphor-icons/react/dist/ssr";
import { C } from "@/lib/connected/copy";
import { intakePath } from "@/lib/connected/matter";
import { navFor } from "@/lib/connected/me";
import { PATHS } from "@/lib/connected/routes";
import { requireConnected } from "@/lib/connected/server-gate";
import { loadViewer } from "@/lib/connected/viewer";
import { ConnectedFrame, PageSkeleton } from "../_components/ConnectedFrame";
import { ViewerProblem } from "../_components/ViewerProblem";
import { ConnectedIntake } from "./ConnectedIntake";
import { SessionPanel } from "./SessionPanel";
import styles from "../../workbench/intake/intake.module.css";

/** The intake intro in connected mode: the development notice replaces the preview notice. */
function IntakeIntro() {
  return (
    <section className={styles.intro} aria-labelledby="page-title">
      <h1 id="page-title" className={styles.statement}>
        Open a matter and record its conflict check.
      </h1>
      <p className={styles.lede}>Work on a matter starts only after a lawyer records the conflict result.</p>
      <p className={styles.synthetic}>
        <Flask weight="bold" aria-hidden="true" focusable="false" />
        {C.C90}
      </p>
    </section>
  );
}

async function IntakeContent({ matterId }: { matterId: string | null }) {
  const config = await requireConnected();
  const path = intakePath(matterId);
  const viewer = await loadViewer(config);
  if (viewer.kind === "unlinked") redirect(PATHS.notLinked);
  if (viewer.kind === "signed_out" || viewer.kind === "rejected") {
    return (
      <ConnectedFrame signedIn={viewer.kind === "rejected"}>
        <IntakeIntro />
        <SessionPanel kind={viewer.kind === "signed_out" ? "signed_out" : "not_set_up"} returnTo={path} />
      </ConnectedFrame>
    );
  }
  if (viewer.kind === "unavailable") {
    return (
      <ConnectedFrame signedIn>
        <ViewerProblem kind="unavailable" retryHref={path} />
      </ConnectedFrame>
    );
  }
  // A platform administrator outside any organization has no matters to open.
  if (viewer.me.organization === null) redirect(PATHS.account);
  return (
    <ConnectedFrame nav={navFor(viewer.me, path)} signedIn>
      <IntakeIntro />
      <ConnectedIntake key={matterId ?? "new"} matterId={matterId} subject={viewer.subject ?? null} />
    </ConnectedFrame>
  );
}

/** Connected intake for /workbench/intake (new) and /workbench/intake/<id> (resume). */
export function IntakeRoute({ matterId }: { matterId: string | null }) {
  return (
    <Suspense
      fallback={
        <ConnectedFrame>
          <PageSkeleton label="Loading intake." />
        </ConnectedFrame>
      }
    >
      <IntakeContent matterId={matterId} />
    </Suspense>
  );
}
