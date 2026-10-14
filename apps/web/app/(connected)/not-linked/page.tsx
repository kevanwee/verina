import type { Metadata } from "next";
import { Suspense } from "react";
import { redirect } from "next/navigation";
import { ACCOUNT } from "@/lib/connected/copy-accounts";
import { DEFAULT_SIGNED_IN_PATH, PATHS } from "@/lib/connected/routes";
import { requireConnected } from "@/lib/connected/server-gate";
import { loadViewer } from "@/lib/connected/viewer";
import { ConnectedFrame, PageSkeleton } from "../_components/ConnectedFrame";
import { NotLinked } from "../_components/NotLinked";
import { ViewerProblem } from "../_components/ViewerProblem";

export const metadata: Metadata = {
  title: "Account not linked | Verina",
  robots: { index: false, follow: false },
};

async function NotLinkedContent() {
  const config = await requireConnected();
  const viewer = await loadViewer(config);
  if (viewer.kind === "signed_out") redirect(PATHS.signIn);
  if (viewer.kind === "linked") redirect(DEFAULT_SIGNED_IN_PATH);
  return (
    <ConnectedFrame signedIn>
      {viewer.kind === "unlinked" ? (
        <NotLinked />
      ) : (
        <ViewerProblem kind={viewer.kind} retryHref={PATHS.notLinked} />
      )}
    </ConnectedFrame>
  );
}

export default function NotLinkedPage() {
  return (
    <Suspense
      fallback={
        <ConnectedFrame>
          <PageSkeleton label={ACCOUNT.TITLE} />
        </ConnectedFrame>
      }
    >
      <NotLinkedContent />
    </Suspense>
  );
}
