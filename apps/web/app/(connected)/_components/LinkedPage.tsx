import { Suspense, type ReactNode } from "react";
import { notFound } from "next/navigation";
import { navFor, type LinkedMe } from "@/lib/connected/me";
import { requireConnected } from "@/lib/connected/server-gate";
import { requireLinked } from "@/lib/connected/viewer";
import { ConnectedFrame, PageSkeleton } from "./ConnectedFrame";
import { ViewerProblem } from "./ViewerProblem";

export type LinkedProps = { me: LinkedMe; subject: string | null };

async function LinkedContent({
  path,
  allow,
  render,
}: {
  path: string;
  allow?: (me: LinkedMe) => boolean;
  render: (props: LinkedProps) => ReactNode;
}) {
  const config = await requireConnected();
  const viewer = await requireLinked(config, path);
  if (viewer.kind !== "linked") {
    return (
      <ConnectedFrame signedIn>
        <ViewerProblem kind={viewer.kind} retryHref={path} />
      </ConnectedFrame>
    );
  }
  // Interface-level check only; the API answers a uniform 404 to anyone not permitted.
  if (allow && !allow(viewer.me)) notFound();
  return (
    <ConnectedFrame nav={navFor(viewer.me, path)} signedIn>
      {render({ me: viewer.me, subject: viewer.subject ?? null })}
    </ConnectedFrame>
  );
}

/**
 * A connected page for a linked account. The request-time part (session, /v1/me) streams
 * behind Suspense with a static skeleton, as Cache Components requires.
 */
export function LinkedPage(props: {
  path: string;
  loadingLabel: string;
  allow?: (me: LinkedMe) => boolean;
  render: (props: LinkedProps) => ReactNode;
}) {
  return (
    <Suspense
      fallback={
        <ConnectedFrame>
          <PageSkeleton label={props.loadingLabel} />
        </ConnectedFrame>
      }
    >
      <LinkedContent path={props.path} allow={props.allow} render={props.render} />
    </Suspense>
  );
}
