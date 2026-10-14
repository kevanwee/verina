"use client";

import { useEffect } from "react";
import { broadcastAuth, type AuthMessage } from "@/lib/connected/auth/client";

/** Tells other open Verina tabs that this tab signed in or out (identity-change checks). */
export function AuthBroadcast({ message }: { message: AuthMessage["type"] }) {
  useEffect(() => {
    broadcastAuth({ type: message });
  }, [message]);
  return null;
}
