/**
 * Motion tokens and helpers for Verina.
 *
 * Rules (see docs/design/DESIGN_SYSTEM.md, "Motion"):
 * - Motion explains a state change. It is never decoration.
 * - Work surfaces (ledger, grid, redline) use durations of 300 ms or less.
 * - Everything has a reduced-motion fallback: content is visible and static by default,
 *   and animations only run under `(prefers-reduced-motion: no-preference)`.
 *
 * Import GSAP from this module (not from "gsap" directly) so plugins are registered once.
 */
import { useSyncExternalStore } from "react";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

let registered = false;

/** Registers GSAP plugins exactly once, and only in the browser. */
export function registerMotionPlugins(): void {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(ScrollTrigger, useGSAP);
  registered = true;
}

registerMotionPlugins();

/** Durations in seconds (GSAP units). Mirrors the `--duration-*` CSS tokens in globals.css. */
export const duration = {
  instant: 0,
  /** Hover, press and focus feedback. */
  fast: 0.12,
  /** Default state change: a status update, a row expanding. */
  base: 0.2,
  /** Upper bound for any motion on a work surface. */
  slow: 0.3,
} as const;

/** Delay between items in a staggered reveal, in seconds. */
export const stagger = 0.04;

/** Easings. GSAP names first, CSS equivalents mirror the `--ease-*` tokens. */
export const ease = {
  /** Things arriving or settling: exponential-style ease-out. */
  out: "power3.out",
  /** Things moving between two on-screen positions. */
  inOut: "power2.inOut",
} as const;

export const cssEase = {
  out: "cubic-bezier(0.22, 1, 0.36, 1)",
  inOut: "cubic-bezier(0.65, 0, 0.35, 1)",
} as const;

/** Media query used for every motion gate. */
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
/** The inverse, for `gsap.matchMedia().add(...)`. */
export const MOTION_OK_QUERY = "(prefers-reduced-motion: no-preference)";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mql = window.matchMedia(REDUCED_MOTION_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return true;
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/** On the server we assume reduced motion: nothing animates until the client says it may. */
function getServerSnapshot(): boolean {
  return true;
}

/**
 * `true` when the user asked for reduced motion (or before hydration).
 * Re-renders when the OS setting changes.
 */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export { gsap, ScrollTrigger, useGSAP };
