import type { Metadata } from "next";
import { Suspense } from "react";
import { cookies } from "next/headers";
import { RETURN_TO_COOKIE } from "@/lib/connected/sign-in-flow";
import { redirect } from "next/navigation";
import { getSession } from "@/lib/connected/auth/server";
import { AUTH } from "@/lib/connected/copy-accounts";
import { TITLES } from "@/lib/connected/copy";
import { safeReturnTo } from "@/lib/connected/return-to";
import { DEFAULT_SIGNED_IN_PATH } from "@/lib/connected/routes";
import { requireConnected } from "@/lib/connected/server-gate";
import { ConnectedFrame, PageSkeleton } from "../_components/ConnectedFrame";
import { signInAction } from "./actions";
import { SignInForm, type SignInNotice } from "./SignInForm";

export const metadata: Metadata = {
  title: TITLES.signIn,
  robots: { index: false, follow: false },
};

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

async function SignInContent({ searchParams }: { searchParams: PageProps<"/sign-in">["searchParams"] }) {
  const config = await requireConnected();
  const params = await searchParams;
  const returnTo = safeReturnTo(first(params.returnTo)) ??
    safeReturnTo((await cookies()).get(RETURN_TO_COOKIE)?.value);
  const signedOut = first(params.signedOut) === "1";
  const notice: SignInNotice = first(params.error) === "link" ? "link" : signedOut ? "signed_out" : null;

  if (!signedOut) {
    const session = await getSession(config);
    if (session.state === "signed_in") redirect(new URL(returnTo ?? DEFAULT_SIGNED_IN_PATH, config.publicOrigin).href);
  }

  return <SignInForm action={signInAction} returnTo={returnTo} notice={notice} />;
}

export default function SignInPage({ searchParams }: PageProps<"/sign-in">) {
  return (
    <ConnectedFrame>
      <Suspense fallback={<PageSkeleton label={AUTH.SIGN_IN_TITLE} />}>
        <SignInContent searchParams={searchParams} />
      </Suspense>
    </ConnectedFrame>
  );
}
