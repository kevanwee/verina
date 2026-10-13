import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no matchMedia. GSAP's matchMedia and useReducedMotion need it.
// Default to "reduce" so components render their static, no-motion state in tests.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: query.includes("prefers-reduced-motion: reduce"),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

afterEach(() => {
  cleanup();
});
