import type { Metadata } from "next";
import Link from "next/link";
import { Flask } from "@phosphor-icons/react/dist/ssr";
import { IntakePrototype } from "./IntakePrototype";
import shell from "../page.module.css";
import styles from "./intake.module.css";

export const metadata: Metadata = {
  title: "Intake prototype | Verina",
  description: "Synthetic prototype of matter intake and the conflict check.",
  robots: { index: false, follow: false },
};

export default function IntakePage() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className={shell.topbar}>
        <div className={shell.topbarInner}>
          <p className={shell.wordmark}>Verina demo</p>
          <nav aria-label="Workspace" className={shell.nav}>
            <ul>
              <li>
                <Link href="/">Home</Link>
              </li>
              <li>
                <Link href="/workbench">Ledger</Link>
              </li>
              <li>
                <Link href="/workbench/intake" aria-current="page">
                  Intake
                </Link>
              </li>
            </ul>
          </nav>
        </div>
      </header>

      <main id="main" tabIndex={-1} className={shell.main}>
        <section className={styles.intro} aria-labelledby="page-title">
          <h1 id="page-title" className={styles.statement}>
            Open a matter and record its conflict check.
          </h1>
          <p className={styles.lede}>
            Work on a matter starts only after a lawyer records the conflict
            result under their name. Switch the view to see what the requester
            sees.
          </p>
          <p className={styles.synthetic}>
            <Flask weight="bold" aria-hidden="true" focusable="false" />
            Synthetic prototype. Use invented examples only. Demo entries stay in this
            page&apos;s memory and reset on reload; nothing is uploaded or sent by this walkthrough.
          </p>
        </section>

        <IntakePrototype />
      </main>

      <footer className={shell.footer}>
        <p>All matters, parties and people on this page are synthetic.</p>
      </footer>
    </>
  );
}
