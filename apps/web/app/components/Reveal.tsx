"use client";

import { useRef, type ReactNode } from "react";
import {
  MOTION_OK_QUERY,
  duration,
  ease,
  gsap,
  stagger,
  useGSAP,
} from "@/lib/motion";

/**
 * A restrained arrival for the landing page's supporting actions and note.
 *
 * Headline, explanatory text and ledger proof stay immediately visible. They
 * must never wait for hydration or an opacity tween to become an LCP candidate.
 *
 * - Content is fully visible in the server HTML; GSAP only animates *from* a
 *   hidden state, so no-JS and reduced-motion users see a static page.
 * - Runs only under `(prefers-reduced-motion: no-preference)` via gsap.matchMedia.
 * - Every tween is <= 300 ms (work-surface limit). useGSAP reverts on unmount.
 */
export function Reveal({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MOTION_OK_QUERY, () => {
        // A page opened in a background tab gets no animation frames; never
        // leave content parked in its hidden "from" state.
        if (document.visibilityState !== "visible") return;
        const tl = gsap.timeline({ defaults: { ease: ease.out } });
        tl.from("[data-reveal]", {
          autoAlpha: 0,
          y: 8,
          duration: duration.slow,
          stagger,
        });
      });
      return () => mm.revert();
    },
    { scope },
  );

  return (
    <div ref={scope} className={className}>
      {children}
    </div>
  );
}
