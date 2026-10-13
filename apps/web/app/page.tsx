import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, ArrowDown } from "@phosphor-icons/react/dist/ssr";
import { Reveal } from "./components/Reveal";
import { LedgerPreview } from "./components/LedgerPreview";
import { StatusStamp } from "./components/ledger/StatusStamp";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "Verina | Every assertion accounted for",
  description: "Explore a prototype of Verina, an AI workbench for contract matters. See assertions, their sources and the decisions that need a lawyer.",
};

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link className={styles.wordmark} href="/" aria-label="Verina home">Verina</Link>
          <nav aria-label="Main navigation" className={styles.nav}>
            <a href="#approach">The approach</a>
            <Link className={styles.navDemo} href="/workbench">Explore the demo <ArrowRight weight="bold" aria-hidden="true" /></Link>
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1} className={styles.main}>
        <Reveal className={styles.hero}>
          <section className={styles.heroCopy} aria-labelledby="hero-heading">
            <h1 id="hero-heading" className={styles.headline}>Every assertion.<br /> <em>Accounted for.</em></h1>
            <p className={styles.lede}>AI-assisted contract review, with the source beside the claim and the lawyer at the centre of every decision.</p>
            <div className={styles.heroActions} data-reveal="">
              <Link className={styles.primaryLink} href="/workbench">Explore the workbench <ArrowRight weight="bold" aria-hidden="true" /></Link>
              <a className={styles.textLink} href="#approach">See how it works <ArrowDown weight="bold" aria-hidden="true" /></a>
            </div>
            <p className={styles.demoNote} data-reveal="">A working prototype for Singapore legal teams.<br />The demo uses synthetic examples only.</p>
          </section>
          <div className={styles.heroProof}><LedgerPreview /></div>
        </Reveal>
        <div className={styles.audience}>
          <p>Built around the judgement of</p>
          <ul><li>Law firm associates</li><li>Reviewing partners</li><li>In-house counsel</li></ul>
        </div>
        <section id="approach" className={styles.approach} aria-labelledby="approach-heading">
          <div className={styles.sectionIntro}>
            <h2 id="approach-heading">From a plausible answer<br /> to a defensible decision.</h2>
            <p>A draft is a starting point. The Verification Ledger makes each assertion visible, so a lawyer can examine what supports it.</p>
          </div>
          <ol className={styles.steps}>
            <li><span className={styles.stepNumber} aria-hidden="true">01</span><div><h3>Read the assertion</h3><p>Review a specific claim, separated from the rest of the draft. Know exactly what needs checking.</p></div></li>
            <li><span className={styles.stepNumber} aria-hidden="true">02</span><div><h3>Inspect its source</h3><p>Compare the claim with the quoted clause. Missing evidence and contradictions stay visible.</p></div></li>
            <li><span className={styles.stepNumber} aria-hidden="true">03</span><div><h3>Own the decision</h3><p>The intended delivery gate requires verification or a named lawyer’s attestation for every assertion.</p></div></li>
          </ol>
        </section>
        <section className={styles.accountability} aria-labelledby="accountability-heading">
          <div className={styles.sectionIntro}>
            <h2 id="accountability-heading">A status that says<br /> what still needs work.</h2>
            <p>Four explicit statuses distinguish evidence from judgement. Labels and shapes carry the meaning alongside colour.</p>
            <Link className={styles.textLink} href="/workbench#ledger">Inspect the sample ledger <ArrowRight weight="bold" aria-hidden="true" /></Link>
          </div>
          <dl className={styles.statusList}>
            <div><dt><StatusStamp status="verified" /></dt><dd>The source supports the assertion.</dd></div>
            <div><dt><StatusStamp status="unsupported" /></dt><dd>No supporting source has been found. Review stays open.</dd></div>
            <div><dt><StatusStamp status="contradicted" /></dt><dd>The source says something different. Review stays open.</dd></div>
            <div><dt><StatusStamp status="attested" /></dt><dd>A named lawyer takes responsibility and records a reason.</dd></div>
          </dl>
        </section>
        <section id="demo-notice" className={styles.demoDisclosure} aria-labelledby="demo-heading">
          <h2 id="demo-heading">Start with the evidence.</h2>
          <p>Explore a sample agreement, inspect its assertions and see why unresolved entries keep the export gate closed.</p>
          <Link className={styles.primaryLink} href="/workbench">Open the synthetic demo <ArrowRight weight="bold" aria-hidden="true" /></Link>
          <p className={styles.disclosure}>This is a read-only prototype, not legal advice. It does not accept uploads, run live AI checks or send client documents. All clauses, parties and people in the demo are invented.</p>
        </section>
      </main>
      <footer className={styles.footer}>
        <Link className={styles.wordmark} href="/" aria-label="Verina home">Verina</Link>
        <p>A considered decision starts with a clear source.</p>
        <a href="#demo-notice">About this prototype</a>
      </footer>
    </>
  );
}
