"use client";

import { useEffect, useState, type RefObject } from "react";
import { CheckCircle } from "@phosphor-icons/react/dist/ssr";
import styles from "../connected.module.css";

/**
 * The single polite live region for a console: "Saving." while a request is slow, then the
 * confirmed result as persistent text (not a timed toast). The region is always in the DOM
 * so screen readers announce changes to it.
 */
export function LiveStatus({ message, confirmed }: { message: string | null; confirmed: boolean }) {
  return (
    <div role="status" aria-live="polite">
      {message ? (
        <p className={styles.status}>
          {confirmed ? <CheckCircle weight="bold" aria-hidden="true" focusable="false" /> : null}
          {message}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Moves focus after the next render, once error text and aria-describedby are in place,
 * so the field is announced with its error.
 */
export function useFocusAfterRender() {
  const [target, setTarget] = useState<{ ref: RefObject<HTMLElement | null> } | null>(null);
  useEffect(() => {
    target?.ref.current?.focus();
  }, [target]);
  return (ref: RefObject<HTMLElement | null>) => setTarget({ ref });
}

/** Stable ref map keyed by string (row action buttons that must regain focus). */
export function useRefMap<T extends HTMLElement>() {
  const [api] = useState(() => {
    const map = new Map<string, T>();
    return {
      set: (key: string) => (element: T | null) => {
        if (element) map.set(key, element);
        else map.delete(key);
      },
      get: (key: string) => map.get(key) ?? null,
    };
  });
  return api;
}
