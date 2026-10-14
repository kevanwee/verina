import type { Metadata } from "next";
import { Suspense } from "react";
import { ACCOUNT } from "@/lib/connected/copy-accounts";
import { navFor } from "@/lib/connected/me";
import { PATHS } from "@/lib/connected/routes";
import { requireConnected } from "@/lib/connected/server-gate";
import { requireLinked } from "@/lib/connected/viewer";
import { ConnectedFrame, PageSkeleton } from "../_components/ConnectedFrame";
import { AccountDetails } from "../_components/AccountDetails";
import { ViewerProblem } from "../_components/ViewerProblem";

export const metadata: Metadata = {
  title: "Your account | Verina",
  robots: { index: false, follow: false },
};

async function AccountContent() {
  const config = await requireConnected();
  const viewer = await requireLinked(config, PATHS.account);
  if (viewer.kind !== "linked") {
    return (
      <ConnectedFrame signedIn>
        <ViewerProblem kind={viewer.kind} retryHref={PATHS.account} />
      </ConnectedFrame>
    );
  }
  return (
    <ConnectedFrame nav={navFor(viewer.me, PATHS.account)} signedIn>
      <AccountDetails me={viewer.me} />
    </ConnectedFrame>
  );
}

export default function AccountPage() {
  return (
    <Suspense
      fallback={
        <ConnectedFrame>
          <PageSkeleton label={ACCOUNT.TITLE} />
        </ConnectedFrame>
      }
    >
      <AccountContent />
    </Suspense>
  );
}
