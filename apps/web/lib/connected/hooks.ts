"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getSession, onIdentityChange, reauthenticate } from "./auth/client";
import {
  apiRead,
  freeze,
  keepsKey,
  sendFrozen,
  type FrozenRequest,
  type Outcome,
  type RequestOptions,
} from "./request";

export type MutationState<T> =
  | { phase: "idle" }
  | { phase: "pending"; frozen: FrozenRequest; slow: boolean }
  | { phase: "settled"; frozen: FrozenRequest | null; outcome: Outcome<T> };

/** "Saving." is announced only if a request is still pending after this long. */
export const SLOW_AFTER_MS = 500;

/**
 * One user action = one frozen request with its own Idempotency-Key. While a request is in
 * flight further activations are ignored. After network loss, 503 or 401 the frozen request
 * is kept, and retry() re-sends it byte for byte with the same key. Any other outcome
 * discards the key.
 */
export function useFrozenMutation<T = unknown>(options?: RequestOptions) {
  const [state, setState] = useState<MutationState<T>>({ phase: "idle" });
  const inFlight = useRef(false);
  const frozenRef = useRef<FrozenRequest | null>(null);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  const run = useCallback(async (frozen: FrozenRequest): Promise<Outcome<T> | null> => {
    if (inFlight.current) return null;
    inFlight.current = true;
    frozenRef.current = frozen;
    setState({ phase: "pending", frozen, slow: false });
    const timer = setTimeout(() => {
      setState((current) =>
        current.phase === "pending" && current.frozen === frozen ? { ...current, slow: true } : current,
      );
    }, SLOW_AFTER_MS);
    const outcome = await sendFrozen<T>(frozen, optionsRef.current);
    clearTimeout(timer);
    inFlight.current = false;
    const keep = keepsKey(outcome);
    if (!keep) frozenRef.current = null;
    setState({ phase: "settled", frozen: keep ? frozen : null, outcome });
    return outcome;
  }, []);

  const submit = useCallback(
    (method: FrozenRequest["method"], path: string, body: unknown, ifMatch?: string) => {
      if (inFlight.current || frozenRef.current !== null) return Promise.resolve(null);
      return run(freeze(method, path, body, ifMatch));
    },
    [run],
  );

  const retry = useCallback(() => {
    const frozen = frozenRef.current;
    return frozen ? run(frozen) : Promise.resolve(null);
  }, [run]);

  const reset = useCallback(() => {
    if (inFlight.current) return;
    frozenRef.current = null;
    setState({ phase: "idle" });
  }, []);

  const pending = state.phase === "pending";
  /** Inputs stay read-only while a request is pending or kept for retry. */
  const locked = pending || (state.phase === "settled" && state.frozen !== null);
  const outcome = state.phase === "settled" ? state.outcome : null;
  const slow = state.phase === "pending" && state.slow;
  return { state, outcome, pending, locked, slow, submit, retry, reset };
}

/**
 * Purges the page (by reloading it) when a different person signs in or this session signs
 * out in another tab, so one account's data is never shown under another.
 */
export function useIdentityGuard(subject: string | null) {
  useEffect(() => {
    if (subject === null) return;
    return onIdentityChange(subject, () => window.location.reload());
  }, [subject]);
}

/**
 * "Sign in again" for a 401: signs in without unloading the page, then re-sends the kept
 * request with the same key. If someone else signed in, the page is purged instead.
 */
export function useReauthenticate(subject: string | null, retry: () => unknown) {
  return useCallback(async () => {
    const result = await reauthenticate();
    if (result !== "signed-in") return;
    try {
      const session = await getSession();
      if (session.subject !== subject) {
        window.location.reload();
        return;
      }
    } catch {
      // Unknown session state: retrying is still safe, the key is unchanged.
    }
    retry();
  }, [subject, retry]);
}

export type ResourceState<T> =
  | { status: "loading" }
  | { status: "loaded"; data: T }
  | { status: "failed"; outcome: Outcome };

/**
 * GET through the proxy on mount, plus reload() for after a confirmed change. An answer
 * that does not parse is shown as "unavailable", never guessed at.
 */
export function useResource<T>(path: string, parse: (json: unknown) => T | null) {
  const [state, setState] = useState<ResourceState<T>>({ status: "loading" });
  const parseRef = useRef(parse);
  useEffect(() => {
    parseRef.current = parse;
  });

  const apply = useCallback((outcome: Outcome) => {
    if (outcome.kind !== "ok") {
      setState({ status: "failed", outcome });
      return;
    }
    const data = parseRef.current(outcome.data);
    setState(data === null ? { status: "failed", outcome: { kind: "unavailable" } } : { status: "loaded", data });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void apiRead(path).then((outcome) => {
      if (!cancelled) apply(outcome);
    });
    return () => {
      cancelled = true;
    };
  }, [path, apply]);

  const reload = useCallback(async () => {
    apply(await apiRead(path));
  }, [path, apply]);

  return { state, reload };
}
