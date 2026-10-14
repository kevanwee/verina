import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ID_SEGMENT } from "@/lib/connected/routes";
import { ConnectedFrame, PageSkeleton } from "../../_components/ConnectedFrame";
import { IntakeRoute } from "../IntakeRoute";

/* Served at /workbench/intake/<matter id> through the proxy rewrite. */

export const metadata: Metadata = {
  // The client sets "Matter <reference> | Verina" once the matter loads; never the title.
  title: "Matter | Verina",
  robots: { index: false, follow: false },
};

async function ResumeRoute({ params }: { params: PageProps<"/intake-connected/[matterId]">["params"] }) {
  const { matterId } = await params;
  if (!ID_SEGMENT.test(matterId)) notFound();
  return <IntakeRoute matterId={matterId} />;
}

export default function ResumeMatterPage({ params }: PageProps<"/intake-connected/[matterId]">) {
  return (
    <Suspense
      fallback={
        <ConnectedFrame>
          <PageSkeleton label="Loading matter." />
        </ConnectedFrame>
      }
    >
      <ResumeRoute params={params} />
    </Suspense>
  );
}
