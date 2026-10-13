import {
  CircleDashed,
  PenNib,
  SealCheck,
  XCircle,
} from "@phosphor-icons/react/dist/ssr";
import type { Icon } from "@phosphor-icons/react";
import { STATUS_META, type LedgerStatus } from "@/lib/ledger";
import styles from "./ledger.module.css";

const STATUS_ICON: Record<LedgerStatus, Icon> = {
  verified: SealCheck, // closed seal with a tick: checked against source
  unsupported: CircleDashed, // broken outline: nothing behind it
  contradicted: XCircle, // cross: source disagrees
  attested: PenNib, // pen: a named lawyer signed for it
};

type StatusStampProps = {
  status: LedgerStatus;
  /** Optional imprint line, e.g. "13 Oct 2026" or "N. Lim, 13 Oct 2026". */
  detail?: string;
};

/**
 * A ledger status, readable three ways: label text, icon shape, and colour.
 * Screen readers hear "Ledger status: <label>" followed by the detail.
 */
export function StatusStamp({ status, detail }: StatusStampProps) {
  const { label } = STATUS_META[status];
  const StatusIcon = STATUS_ICON[status];

  return (
    <span className={styles.stamp} data-status={status} data-reveal-stamp="">
      <span className={styles.stampHead}>
        <StatusIcon
          className={styles.stampIcon}
          weight="bold"
          aria-hidden="true"
          focusable="false"
        />
        <span>
          <span className="visually-hidden">Ledger status: </span>
          {label}
        </span>
      </span>
      {detail ? (
        <span className={styles.stampDetail}>
          <span className="visually-hidden">, by </span>
          {detail}
        </span>
      ) : null}
    </span>
  );
}
