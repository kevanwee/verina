"use client";
import { useState } from "react";
import { ArrowDown, LockSimple } from "@phosphor-icons/react/dist/ssr";
import { SAMPLE_LEDGER } from "@/lib/sample-ledger";
import { STATUS_META } from "@/lib/ledger";
import { StatusStamp } from "./ledger/StatusStamp";
import styles from "./ledger-preview.module.css";

const EXAMPLES = [
  { label: "Liability", entry: SAMPLE_LEDGER[0] },
  { label: "Termination", entry: SAMPLE_LEDGER[1] },
  { label: "Governing law", entry: SAMPLE_LEDGER[2] },
] as const;

export function LedgerPreview() {
  const [selected, setSelected] = useState(0);
  const entry = EXAMPLES[selected].entry;
  const blocked = STATUS_META[entry.status].blocksExport;
  return (
    <section className={styles.preview} aria-labelledby="preview-heading">
      <div className={styles.heading}><h2 id="preview-heading">The Verification Ledger</h2><span>Interactive sample</span></div>
      <fieldset className={styles.examples}>
        <legend className="visually-hidden">Choose a sample assertion</legend>
        {EXAMPLES.map((example, index) => <button key={example.entry.id} type="button" aria-pressed={selected === index} aria-controls="preview-assertion" onClick={() => setSelected(index)}>{example.label}</button>)}
      </fieldset>
      <div id="preview-assertion" className={styles.entry} aria-live="polite" aria-atomic="true">
        <div className={styles.entryTop}><span className={styles.entryId}>{entry.id}</span><StatusStamp status={entry.status} /></div>
        <h3 className={styles.assertion}>{entry.assertion}</h3>
        <div className={styles.sourceLabel}><span>Check against the source</span><ArrowDown weight="bold" aria-hidden="true" /></div>
        {entry.source.kind === "quote" ? (
          <figure className={styles.source}>
            <blockquote>{entry.source.text}</blockquote>
            <figcaption>{entry.source.citation}</figcaption>
          </figure>
        ) : <p className={styles.missingSource}>{entry.source.searched}</p>}
        <p className={styles.finding}>{entry.note ?? (blocked ? "This assertion needs a supporting source or a lawyer’s attestation." : "The source supports this assertion. Other open entries still block the sample matter’s export.")}</p>
      </div>
      <div className={styles.gate}><LockSimple weight="bold" aria-hidden="true" /><p><strong>Review before delivery</strong><span>Unresolved entries keep the gate closed.</span></p></div>
      <p className={styles.caption}>Synthetic clauses. Statuses are preset to illustrate the workflow.</p>
    </section>
  );
}
