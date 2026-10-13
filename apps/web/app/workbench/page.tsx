import { LockSimple } from "@phosphor-icons/react/dist/ssr";
import { LedgerEntry } from "../components/ledger/LedgerEntry";
import Link from "next/link";
import { RiskTierBadge } from "../components/ledger/RiskTierBadge";
import { StatusStamp } from "../components/ledger/StatusStamp";
import {
  LEDGER_STATUSES,
  RISK_TIERS,
  STATUS_META,
  TIER_META,
} from "@/lib/ledger";
import { SAMPLE_LEDGER, SAMPLE_MATTER } from "@/lib/sample-ledger";
import styles from "./page.module.css";

export default function Workbench() {
  // Open entries (the ones blocking export) come first: they are the work.
  const openEntries = SAMPLE_LEDGER.filter(
    (entry) => STATUS_META[entry.status].blocksExport,
  );
  const clearedEntries = SAMPLE_LEDGER.filter(
    (entry) => !STATUS_META[entry.status].blocksExport,
  );
  const ledger = [...openEntries, ...clearedEntries];
  const blocking = openEntries.length;
  const cleared = clearedEntries.length;

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <h1 className={styles.wordmark}>Verina demo</h1>
          <nav aria-label="Workspace" className={styles.nav}>
            <ul>
              <li><Link href="/">Home</Link></li>
              <li>
                <a href="#ledger">Ledger</a>
              </li>
              <li>
                <a href="#statuses">Statuses</a>
              </li>
            </ul>
          </nav>
        </div>
      </header>

      <main id="main" tabIndex={-1} className={styles.main}>
        <div className={styles.workspace}>
          <section className={styles.intro} aria-labelledby="statement">
            <h2 id="statement" className={styles.statement} data-reveal="">
              See the verification gate at work.
            </h2>
            <p className={styles.lede} data-reveal="">
              This sample shows how claims, sources and a lawyer’s attestation
              fit together. Its verification statuses are preset.
            </p>

            <section
              className={styles.matter}
              aria-labelledby="matter-title"
              data-reveal=""
            >
              <h3 id="matter-title" className={styles.matterTitle}>
                {SAMPLE_MATTER.title}
              </h3>
              <p className={styles.synthetic}>Read-only demonstration. Synthetic data; no live verification or export.</p>

              <dl className={styles.facts}>
                <div>
                  <dt>Risk tier</dt>
                  <dd>
                    <RiskTierBadge tier={SAMPLE_MATTER.tier} />
                  </dd>
                </div>
                <div>
                  <dt>Agreement</dt>
                  <dd>{SAMPLE_MATTER.type}</dd>
                </div>
                <div>
                  <dt>Ledger</dt>
                  <dd>
                    {SAMPLE_LEDGER.length} entries, {cleared} cleared,{" "}
                    {blocking} open
                  </dd>
                </div>
              </dl>

              <div className={styles.gate}>
                <p id="gate-reason" className={styles.gateReason}>
                  <LockSimple
                    className={styles.gateIcon}
                    weight="bold"
                    aria-hidden="true"
                    focusable="false"
                  />
                  <span>
                    Export is blocked until{" "}
                    {openEntries.map((entry, index) => (
                      <span key={entry.id}>
                        {index > 0 ? " and " : null}
                        <a href={`#${entry.id}`}>{entry.id}</a>
                      </span>
                    ))}{" "}
                    are verified or attested.
                  </span>
                </p>
                <div className={styles.actions}>
                  <a
                    className={styles.buttonPrimary}
                    href={`#${openEntries[0]?.id ?? "ledger"}`}
                  >
                    Review open entries
                  </a>
                  <button
                    type="button"
                    className={styles.buttonLocked}
                    aria-disabled="true"
                    aria-describedby="gate-reason"
                  >
                    <LockSimple
                      className={styles.buttonIcon}
                      weight="bold"
                      aria-hidden="true"
                      focusable="false"
                    />
                    Export to client
                  </button>
                </div>
              </div>
            </section>
          </section>

          <section
            id="ledger"
            className={styles.ledger}
            aria-labelledby="ledger-heading"
          >
            <div className={styles.ledgerHead} data-reveal="">
              <h2 id="ledger-heading" className={styles.sectionHeading}>
                Verification ledger
              </h2>
              <p className={styles.count}>
                {SAMPLE_LEDGER.length} entries, {blocking} open
              </p>
            </div>
            <ol className={styles.entries}>
              {ledger.map((entry) => (
                <li key={entry.id}>
                  <LedgerEntry entry={entry} />
                </li>
              ))}
            </ol>
          </section>
        </div>

        <section
          id="statuses"
          className={styles.legend}
          aria-labelledby="legend-heading"
        >
          <h2 id="legend-heading" className={styles.sectionHeading}>
            Reading a status
          </h2>
          <div className={styles.legendGrid}>
            <div>
              <h3 className={styles.legendSubhead}>Ledger entries</h3>
              <dl className={styles.legendList}>
                {LEDGER_STATUSES.map((status) => (
                  <div key={status} className={styles.legendRow}>
                    <dt>
                      <StatusStamp status={status} />
                    </dt>
                    <dd>
                      {STATUS_META[status].meaning}{" "}
                      {STATUS_META[status].blocksExport
                        ? "Blocks export."
                        : "Clears export."}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
            <div>
              <h3 className={styles.legendSubhead}>Matter risk tiers</h3>
              <dl className={styles.legendList}>
                {RISK_TIERS.map((tier) => (
                  <div key={tier} className={styles.legendRow}>
                    <dt>
                      <RiskTierBadge tier={tier} />
                    </dt>
                    <dd>{TIER_META[tier].meaning}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <p>All matters, parties and people on this page are synthetic.</p>
      </footer>
    </>
  );
}

