import type { MetadataRoute } from "next";

// Synthetic prototype: ask all crawlers to stay out.
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", disallow: "/" } };
}
