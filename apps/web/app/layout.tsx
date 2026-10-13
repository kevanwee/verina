import type { Metadata } from "next";
import { Atkinson_Hyperlegible_Next, Literata } from "next/font/google";
import { SmoothScroll } from "./providers/SmoothScroll";
import "./globals.css";

/*
 * Atkinson Hyperlegible Next (UI): designed by the Braille Institute so that
 * confusable glyphs differ (I l 1, O 0, rn m). Legal work is full of them:
 * "cl 11.1(l)", "s 10(1)", "[2019] SGCA 1".
 * Literata (legal text): a text serif drawn for long on-screen reading, with an
 * optical-size axis, used for quoted clauses, statutes and judgments.
 */
const atkinson = Atkinson_Hyperlegible_Next({
  subsets: ["latin", "latin-ext"],
  variable: "--font-atkinson",
  display: "swap",
  // Next has no metric overrides for this family yet; fall back without a synthetic font.
  adjustFontFallback: false,
  fallback: ["Segoe UI", "system-ui", "sans-serif"],
});

const literata = Literata({
  subsets: ["latin", "latin-ext"],
  variable: "--font-literata",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Verina",
  description: "Verified AI workbench for contract review",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-SG" className={`${atkinson.variable} ${literata.variable}`}>
      <body>
        <SmoothScroll>{children}</SmoothScroll>
      </body>
    </html>
  );
}
