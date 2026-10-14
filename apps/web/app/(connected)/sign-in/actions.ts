"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { connectedConfig } from "@/lib/connected/config";
import { authFromCookies } from "@/lib/connected/auth/server";
import {
  RETURN_TO_COOKIE,
  runSignIn,
  type SignInState,
} from "@/lib/connected/sign-in-flow";

export async function signInAction(previous: SignInState, formData: FormData): Promise<SignInState> {
  const config = connectedConfig();
  if (config === null || (await headers()).get("origin") !== config.publicOrigin) {
    return { ...previous, error: "unavailable", revision: previous.revision + 1 };
  }
  const outcome = await runSignIn(previous, formData, {
    provider: () => authFromCookies(config),
    origin: config.publicOrigin,
    rememberReturnTo: async (path) => {
      const store = await cookies();
      if (path === null) {
        store.delete({ name: RETURN_TO_COOKIE, path: "/" });
        return;
      }
      // Kept server-side so the emailed link matches the allow-listed callback URL exactly.
      store.set(RETURN_TO_COOKIE, path, {
        httpOnly: true,
        sameSite: "lax",
        secure: config.secureCookies,
        path: "/",
        maxAge: 60 * 60,
      });
    },
  });
  if ("redirectTo" in outcome) {
    (await cookies()).delete({ name: RETURN_TO_COOKIE, path: "/" });
    redirect(new URL(outcome.redirectTo, config.publicOrigin).href);
  }
  return outcome.state;
}
