import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SmoothScroll } from "../app/providers/SmoothScroll";

const motion = vi.hoisted(() => ({ reduced: true, add: vi.fn(), remove: vi.fn(), lagSmoothing: vi.fn(), update: vi.fn() }));
const lenis = vi.hoisted(() => ({ construct: vi.fn(), destroy: vi.fn(), on: vi.fn(), raf: vi.fn() }));
vi.mock("lenis", () => ({ default: class {
  constructor(options: unknown) { lenis.construct(options); }
  destroy = lenis.destroy;
  on = lenis.on;
  raf = lenis.raf;
} }));
vi.mock("@/lib/motion", () => ({
  useReducedMotion: () => motion.reduced,
  gsap: { ticker: { add: motion.add, remove: motion.remove, lagSmoothing: motion.lagSmoothing } },
  ScrollTrigger: { update: motion.update },
}));
describe("SmoothScroll preference lifecycle", () => {
  beforeEach(() => { vi.clearAllMocks(); motion.reduced = true; });
  it("keeps content available and never creates Lenis when motion is reduced", () => {
    render(<SmoothScroll><p>Readable source</p></SmoothScroll>);
    expect(screen.getByText("Readable source")).toBeVisible();
    expect(lenis.construct).not.toHaveBeenCalled();
    expect(motion.add).not.toHaveBeenCalled();
  });
  it("disconnects smoothing when preferences change and cleans up the frame callback", () => {
    motion.reduced = false;
    const { rerender, unmount } = render(<SmoothScroll><p>Readable source</p></SmoothScroll>);
    expect(lenis.construct).toHaveBeenCalledTimes(1);
    expect(lenis.on).toHaveBeenCalledWith("scroll", motion.update);
    const tick = motion.add.mock.calls[0][0] as (time: number) => void;
    tick(1.25);
    expect(lenis.raf).toHaveBeenCalledWith(1250);
    motion.reduced = true;
    rerender(<SmoothScroll><p>Readable source</p></SmoothScroll>);
    expect(lenis.destroy).toHaveBeenCalledTimes(1);
    expect(motion.remove).toHaveBeenCalledWith(tick);
    expect(screen.getByText("Readable source")).toBeVisible();
    motion.reduced = false;
    rerender(<SmoothScroll><p>Readable source</p></SmoothScroll>);
    expect(lenis.construct).toHaveBeenCalledTimes(2);
    unmount();
    expect(lenis.destroy).toHaveBeenCalledTimes(2);
  });
});
