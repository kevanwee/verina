import { describe, expect, it } from "vitest";
import nextConfig, { securityHeaders } from "../next.config";
import robots from "../app/robots";

const header = (key: string) => securityHeaders.find((h) => h.key === key)?.value;

describe("hosted preview hardening", () => {
  it("applies the security headers to every route", async () => {
    const rules = await nextConfig.headers!();
    expect(rules).toEqual([{ source: "/:path*", headers: securityHeaders }]);
  });

  it("forbids framing and plugins", () => {
    expect(header("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    expect(header("Content-Security-Policy")).toContain("object-src 'none'");
    expect(header("X-Frame-Options")).toBe("DENY");
    expect(header("X-Content-Type-Options")).toBe("nosniff");
  });

  it("keeps the prototype out of search indexes", () => {
    expect(header("X-Robots-Tag")).toBe("noindex, nofollow");
    expect(robots().rules).toEqual({ userAgent: "*", disallow: "/" });
  });

  it("does not advertise the framework", () => {
    expect(nextConfig.poweredByHeader).toBe(false);
  });
});
