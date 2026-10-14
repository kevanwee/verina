import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ADMIN } from "@/lib/connected/copy-accounts";
import { adminOrganizationPath, ID_SEGMENT } from "@/lib/connected/routes";
import { ConnectedFrame, PageSkeleton } from "../../../_components/ConnectedFrame";
import { LinkedPage } from "../../../_components/LinkedPage";
import { OrganizationDetail } from "./OrganizationDetail";

export const metadata: Metadata = {
  title: "Organization | Verina",
  robots: { index: false, follow: false },
};

async function OrganizationRoute({ params }: { params: PageProps<"/admin/organizations/[orgId]">["params"] }) {
  const { orgId } = await params;
  if (!ID_SEGMENT.test(orgId)) notFound();
  return (
    <LinkedPage
      path={adminOrganizationPath(orgId)}
      loadingLabel={ADMIN.LOADING_ONE}
      allow={(me) => me.platformAdmin}
      render={({ me, subject }) => (
        <OrganizationDetail orgId={orgId} subject={subject} selfActorId={me.actorId} />
      )}
    />
  );
}

export default function OrganizationPage({ params }: PageProps<"/admin/organizations/[orgId]">) {
  return (
    <Suspense
      fallback={
        <ConnectedFrame>
          <PageSkeleton label={ADMIN.LOADING_ONE} />
        </ConnectedFrame>
      }
    >
      <OrganizationRoute params={params} />
    </Suspense>
  );
}
