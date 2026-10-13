import type { LedgerStatus } from "@/lib/ledger";
import { StatusStamp } from "./StatusStamp";
import styles from "./ledger.module.css";

export type LedgerSource =
  | { kind: "quote"; citation: string; text: string }
  | { kind: "none"; searched: string };

export type LedgerEntryData = {
  id: string;
  assertion: string;
  status: LedgerStatus;
  stampDetail?: string;
  source: LedgerSource;
  /** Reviewer's note: why it is contradicted, or the attestation reason. */
  note?: string;
};

/**
 * One assertion, its source, and its status. The status column has a fixed
 * width so a status change only restyles that cell; the row never reflows.
 */
export function LedgerEntry({ entry }: { entry: LedgerEntryData }) {
  const headingId = `${entry.id}-assertion`;
  return (
    <article
      id={entry.id}
      className={styles.entry}
      data-status={entry.status}
      aria-labelledby={headingId}
      data-reveal=""
    >
      <div className={styles.statusCell}>
        <StatusStamp status={entry.status} detail={entry.stampDetail} />
      </div>
      <div className={styles.body}>
        <p className={styles.entryId}>
          <span className="visually-hidden">Entry </span>
          {entry.id}
        </p>
        <h3 id={headingId} className={styles.assertion}>
          {entry.assertion}
        </h3>
        {entry.source.kind === "quote" ? (
          <figure className={styles.source}>
            <blockquote className={styles.quote}>
              <p>{entry.source.text}</p>
            </blockquote>
            <figcaption className={styles.citation}>
              {entry.source.citation}
            </figcaption>
          </figure>
        ) : (
          <p className={styles.noSource}>{entry.source.searched}</p>
        )}
        {entry.note ? <p className={styles.note}>{entry.note}</p> : null}
      </div>
    </article>
  );
}
