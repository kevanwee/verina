import type { Metadata } from "next";
import { TITLES } from "@/lib/connected/copy";
import { IntakeRoute } from "./IntakeRoute";

/* Served at /workbench/intake through the proxy rewrite when connected mode is on. */

export const metadata: Metadata = {
  title: TITLES.newMatter,
  robots: { index: false, follow: false },
};

export default function ConnectedIntakePage() {
  return <IntakeRoute matterId={null} />;
}
