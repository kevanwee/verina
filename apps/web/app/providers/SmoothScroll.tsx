"use client";

import { useEffect, type ReactNode } from "react";
import Lenis from "lenis";
import "lenis/dist/lenis.css";
import { gsap, ScrollTrigger, useReducedMotion } from "@/lib/motion";

/**
 * One Lenis instance for the whole app, driven by the GSAP ticker so Lenis and
 * ScrollTrigger share a single animation frame loop.
 *
 * Under `prefers-reduced-motion: reduce` Lenis is never created: the page keeps
 * native scrolling (no smoothing, no inertia). If the user flips the OS setting
 * while the page is open, the instance is created or destroyed to match.
 */
export function SmoothScroll({ children }: { children: ReactNode }) {
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    if (reducedMotion) return;

    const lenis = new Lenis({
      autoRaf: false, // the GSAP ticker drives raf (below)
      // In-page links scroll smoothly; the offset clears the sticky header (3.5rem + 1rem).
      anchors: { offset: -72 },
      stopInertiaOnNavigate: true,
    });

    // Keep ScrollTrigger positions in sync with Lenis's virtual scroll.
    lenis.on("scroll", ScrollTrigger.update);

    // GSAP ticker time is in seconds; Lenis expects milliseconds.
    const onTick = (time: number) => {
      lenis.raf(time * 1000);
    };
    gsap.ticker.add(onTick);
    // Lenis already smooths; GSAP's lag compensation would make scroll jump after a long frame.
    gsap.ticker.lagSmoothing(0);

    return () => {
      gsap.ticker.remove(onTick);
      gsap.ticker.lagSmoothing(500, 33); // GSAP default
      lenis.destroy();
    };
  }, [reducedMotion]);

  return <>{children}</>;
}
